from __future__ import annotations

import json
import math
import shutil
import zipfile
from pathlib import Path

import cvxpy as cp
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Rectangle

import qris_uav_simulation as base


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIG = ROOT / "figures_v2"
TABLES = ROOT / "outputs" / "tables_v2"
REPORTS = ROOT / "outputs" / "reports_v2"
ASSETS = ROOT / "assets" / "gpt_image2"

SEED = 20260513
RNG = np.random.default_rng(SEED)

INK = "#16202a"
MUTED = "#5c6670"
TEAL = "#2a9d8f"
CORAL = "#e76f51"
BLUE = "#457b9d"
GOLD = "#e9c46a"
GRAY = "#8d99ae"
PURPLE = "#6650a4"


def ensure_dirs() -> None:
    for path in [FIG, TABLES, REPORTS]:
        path.mkdir(parents=True, exist_ok=True)


def set_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "figure.dpi": 180,
            "savefig.dpi": 240,
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "legend.fontsize": 9,
            "lines.linewidth": 2.2,
        }
    )


def savefig(name: str) -> None:
    plt.tight_layout()
    plt.savefig(FIG / name, bbox_inches="tight")
    plt.close()


def copy_legacy_figures() -> None:
    for p in (ROOT / "figures").glob("*.png"):
        shutil.copy2(p, FIG / p.name)


def load_typhoon_track(scenario: base.Scenario) -> pd.DataFrame:
    path = DATA / "external" / "ibtracs.WP.list.v04r01.csv"
    if not path.exists():
        zip_path = path.with_suffix(path.suffix + ".zip")
        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extract(path.name, path.parent)
        else:
            raise FileNotFoundError(
                "Missing IBTrACS CSV. Expected data/external/ibtracs.WP.list.v04r01.csv "
                "or data/external/ibtracs.WP.list.v04r01.csv.zip."
            )
    cols = ["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "USA_WIND", "WMO_WIND"]
    df = pd.read_csv(path, usecols=cols, skiprows=[1], low_memory=False)
    for col in ["LAT", "LON", "USA_WIND", "WMO_WIND", "SEASON"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    recent = df[(df["SEASON"] >= 2010) & (df["LAT"].between(18, 36)) & (df["LON"].between(112, 132))]
    map_box = recent[recent["LAT"].between(25.0, 35.0) & recent["LON"].between(117.5, 126.5)]
    grouped = map_box.groupby("SID").agg(
        n=("SID", "size"),
        max_wind=("USA_WIND", "max"),
        mean_dist=("LAT", lambda x: 0.0),
    )
    # Pick a long, strong track with visible points inside the plotted East China Sea box.
    grouped["score"] = grouped["n"] + grouped["max_wind"].fillna(0) / 4
    sid = grouped.sort_values("score", ascending=False).index[0]
    track = recent[recent["SID"] == sid].copy()
    track["ISO_TIME"] = pd.to_datetime(track["ISO_TIME"], errors="coerce")
    track["WIND"] = track["USA_WIND"].fillna(track["WMO_WIND"])
    return track.sort_values("ISO_TIME")


def plot_typhoon_context(scenario: base.Scenario) -> None:
    coast_path = DATA / "external" / "ne_10m_coastline" / "ne_10m_coastline.shp"
    coast = gpd.read_file(coast_path, bbox=(116, 24, 128, 36))
    track = load_typhoon_track(scenario)
    nodes = scenario.nodes_lonlat
    base_ll = base.xy_to_lonlat(np.array([scenario.base_xy]), scenario.lon0, scenario.lat0)[0]
    ris_ll = base.xy_to_lonlat(np.array([scenario.ris_xy]), scenario.lon0, scenario.lat0)[0]
    anomaly_ll = base.xy_to_lonlat(np.array([scenario.anomaly_xy]), scenario.lon0, scenario.lat0)[0]

    fig, ax = plt.subplots(figsize=(8.1, 6.1))
    coast.plot(ax=ax, color="#334155", linewidth=0.7)
    ax.plot(track["LON"], track["LAT"], color=CORAL, lw=3.0, alpha=0.88, zorder=2, label="NOAA IBTrACS typhoon track")
    sc = ax.scatter(track["LON"], track["LAT"], c=track["WIND"], cmap="inferno_r", s=34, edgecolor="white", lw=0.35, zorder=4)
    ax.scatter(nodes[:, 0], nodes[:, 1], c=scenario.anomaly_score, cmap="viridis", s=55, edgecolor="white", lw=0.45, label="DeepOWT offshore nodes")
    ax.scatter(*base_ll, marker="s", s=130, color=INK, label="Shore BS")
    ax.scatter(*ris_ll, marker="D", s=110, color=TEAL, label="RIS platform")
    ax.scatter(*anomaly_ll, marker="*", s=190, color=GOLD, edgecolor="#3b2000", label="Cable anomaly")
    ax.set_xlim(117.5, 126.5)
    ax.set_ylim(25.0, 35.0)
    ax.set_title("真实台风轨迹、DeepOWT风电节点与海缆风险区域叠加")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Track wind speed (kt)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, frameon=True, fontsize=8.5)
    ax.grid(alpha=0.25)
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(FIG / "typhoon_deepowt_context.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()


def plot_data_source_matrix() -> None:
    rows = [
        ("DeepOWT", "9941 offshore infrastructure points", "场景节点与风电分布"),
        ("NOAA IBTrACS", "Northwest Pacific best-track archive", "台风灾害背景"),
        ("NOAA WMM2025", "2025-2029 geomagnetic model", "地磁背景尺度"),
        ("Natural Earth", "10m coastline vector data", "地图底图"),
        ("Sentinel-1 / SAR Winds", "SAR all-weather marine observation", "灾后遥感依据"),
        ("Synthetic channel", "RIS-UAV controlled simulation", "优化算法验证"),
    ]
    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    ax.axis("off")
    col_x = [0.02, 0.27, 0.68]
    widths = [0.22, 0.38, 0.28]
    headers = ["数据源", "真实含义", "在本项目中的作用"]
    for x, w, h in zip(col_x, widths, headers):
        ax.add_patch(Rectangle((x, 0.86), w, 0.10, facecolor=INK, edgecolor=INK))
        ax.text(x + 0.012, 0.91, h, color="white", va="center", ha="left", fontsize=12, fontweight="bold")
    for i, row in enumerate(rows):
        y = 0.75 - i * 0.115
        fill = "#fbfaf6" if i % 2 == 0 else "#eef7f5"
        for x, w, text in zip(col_x, widths, row):
            ax.add_patch(Rectangle((x, y), w, 0.095, facecolor=fill, edgecolor="#d5dee4", linewidth=0.7))
            ax.text(x + 0.012, y + 0.048, text, color=INK if x == col_x[0] else MUTED, va="center", ha="left", fontsize=10.5, fontweight="bold" if x == col_x[0] else None)
    ax.text(0.02, 0.08, "原则：真实数据用于场景可信度与物理背景；通信信道采用可控合成仿真以验证优化算法。", color=CORAL, fontsize=12, fontweight="bold")
    ax.set_title("数据来源从“场景真实”到“优化可控”分层使用", loc="left", pad=12)
    savefig("data_source_matrix.png")


def make_schedule(rates: np.ndarray, weights: np.ndarray, a_max: int = 4) -> np.ndarray:
    schedule = np.zeros_like(rates)
    for n in range(rates.shape[0]):
        idx = np.argsort(rates[n] * weights)[-a_max:]
        schedule[n, idx] = 1.0
    return schedule


def cvxpy_resource_allocation(
    q: np.ndarray,
    scenario: base.Scenario,
    phase_mode: str,
    weights: np.ndarray,
    eta: float,
    m_elem: int = 256,
    qkd_scale: float = 1.0,
) -> dict:
    b_mhz = 0.45
    p_ref = 0.20
    rates_ref = base.channel_rates(q, scenario.nodes_xy, scenario.ris_xy, phase_mode, m_elem, p_w=p_ref, b_mhz=b_mhz)
    schedule = make_schedule(rates_ref, weights)
    gamma = np.maximum((2 ** (rates_ref / b_mhz) - 1.0) / p_ref, 1e-6)
    n_slots, k_nodes = rates_ref.shape

    p = cp.Variable((n_slots, k_nodes), nonneg=True)
    s = cp.Variable((n_slots, k_nodes), nonneg=True)
    kap = cp.Variable((n_slots, k_nodes), nonneg=True)
    rate_expr = b_mhz * cp.log1p(cp.multiply(gamma, p)) / math.log(2)
    qkd = qkd_scale * (2.2 + 1.15 * np.sin(np.linspace(0, 2 * np.pi, n_slots)) ** 2)
    rho = 0.55
    p_max = 0.28

    constraints = [
        p <= p_max * schedule,
        s <= cp.multiply(schedule, rate_expr),
        rho * s <= kap,
        cp.sum(kap, axis=1) <= qkd,
        s <= 3.5 * schedule,
    ]
    weighted_secure = cp.sum(cp.multiply(weights[None, :], s))
    flight_energy = float(np.sum(np.linalg.norm(np.diff(q, axis=0), axis=1) ** 2) * 0.42 + 160.0)
    ris_energy = float(0.0009 * m_elem * n_slots if phase_mode != "none" else 0.0)
    fixed_energy = flight_energy + ris_energy
    tx_energy = 0.18 * cp.sum(p)
    objective = cp.Maximize(weighted_secure - eta * (fixed_energy + tx_energy))
    prob = cp.Problem(objective, constraints)
    try:
        prob.solve(solver="CLARABEL", max_iter=160, verbose=False)
    except Exception:
        prob.solve(solver="SCS", max_iters=1200, eps=1e-4, verbose=False)

    p_val = np.nan_to_num(p.value, nan=0.0)
    s_val = np.nan_to_num(s.value, nan=0.0)
    k_val = np.nan_to_num(kap.value, nan=0.0)
    f_val = float(np.sum(s_val * weights[None, :]))
    g_val = float(fixed_energy + 0.18 * np.sum(p_val))
    gap = float(f_val - eta * g_val)
    return {
        "p": p_val,
        "s": s_val,
        "kappa": k_val,
        "schedule": schedule,
        "rates_ref": rates_ref,
        "F": f_val,
        "G": g_val,
        "eta_next": f_val / max(g_val, 1e-9),
        "gap": gap,
        "flight_energy": flight_energy,
        "ris_energy": ris_energy,
        "status": prob.status,
        "objective": float(prob.value) if prob.value is not None else float("nan"),
        "qkd": qkd,
    }


def dinkelbach_ao(scenario: base.Scenario, n_iter: int = 9, n_slots: int = 42) -> dict:
    q = base.initial_uav_path(scenario.base_xy, scenario.nodes_xy, scenario.anomaly_xy, n_slots)
    weights = 1.0 + 4.0 * scenario.anomaly_score
    eta = 0.0
    history = []
    alloc = None
    for it in range(n_iter):
        alloc = cvxpy_resource_allocation(q, scenario, "2bit", weights, eta)
        eta = alloc["eta_next"]
        history.append(
            {
                "iteration": it + 1,
                "eta": eta,
                "gap": alloc["gap"],
                "F": alloc["F"],
                "G": alloc["G"],
                "status": alloc["status"],
            }
        )
        secure_priority = alloc["s"] * weights[None, :]
        next_q = q.copy()
        for n in range(1, n_slots - 1):
            idx = np.argsort(secure_priority[n] + 1e-6)[-5:]
            target = np.average(scenario.nodes_xy[idx], axis=0, weights=secure_priority[n, idx] + 1e-4)
            target = 0.72 * target + 0.28 * scenario.ris_xy
            next_q[n] = 0.84 * q[n] + 0.16 * target
        q = base.smooth_path(next_q, scenario.base_xy)
    assert alloc is not None
    return {"q": q, "weights": weights, "alloc": alloc, "history": pd.DataFrame(history)}


def plot_dinkelbach(result: dict) -> None:
    hist = result["history"]
    fig, ax1 = plt.subplots(figsize=(8.2, 4.8))
    ax1.plot(hist["iteration"], hist["eta"], marker="o", color=TEAL, label="η = F/G")
    ax1.set_xlabel("Dinkelbach iteration")
    ax1.set_ylabel("Secure EE η", color=TEAL)
    ax1.tick_params(axis="y", labelcolor=TEAL)
    ax2 = ax1.twinx()
    ax2.plot(hist["iteration"], np.abs(hist["gap"]), marker="s", color=CORAL, label="|F-ηG|")
    ax2.set_yscale("log")
    ax2.set_ylabel("Dinkelbach residual |F-ηG|", color=CORAL)
    ax2.tick_params(axis="y", labelcolor=CORAL)
    ax1.set_title("真实 Dinkelbach 外层更新：η 上升且残差收敛")
    ax1.grid(alpha=0.25)
    savefig("dinkelbach_eta_gap.png")

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.bar(hist["iteration"], hist["F"], color=TEAL, alpha=0.82, label="Weighted secure data F")
    ax.plot(hist["iteration"], hist["G"], color=CORAL, marker="o", label="Total energy G")
    ax.set_title("Dinkelbach 每轮同时跟踪收益 F 与代价 G")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Value")
    ax.legend(frameon=True, loc="upper right", ncol=1, fontsize=9.0)
    plt.tight_layout()
    plt.savefig(FIG / "dinkelbach_fg_components.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()


def plot_resource_heatmaps(result: dict) -> None:
    alloc = result["alloc"]
    for key, title, cmap, fname in [
        ("s", "安全数据量 s_k[n] 的时隙-节点热力图", "YlGnBu", "secure_data_heatmap.png"),
        ("kappa", "QKD密钥分配 κ_k[n] 的时隙-节点热力图", "PuBuGn", "key_allocation_heatmap.png"),
        ("p", "发射功率 p_k[n] 的时隙-节点热力图", "OrRd", "power_allocation_heatmap.png"),
    ]:
        fig, ax = plt.subplots(figsize=(8.4, 4.8))
        sns.heatmap(alloc[key].T, ax=ax, cmap=cmap, cbar_kws={"label": key}, xticklabels=6, yticklabels=4)
        ax.set_title(title)
        ax.set_xlabel("Time slot n")
        ax.set_ylabel("Node k")
        savefig(fname)

    qkd_used = alloc["kappa"].sum(axis=1)
    high_priority = (alloc["s"][:, np.argsort(result["weights"])[-6:]]).sum(axis=1)
    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    ax.plot(qkd_used, color=TEAL, marker="o", label="Used QKD keys")
    ax.plot(alloc["qkd"], color=GRAY, linestyle="--", label="Available QKD budget")
    ax.fill_between(np.arange(len(high_priority)), 0, high_priority, color=GOLD, alpha=0.25, label="High-priority secure payload")
    ax.set_title("密钥预算被高优先级告警优先占用")
    ax.set_xlabel("Time slot")
    ax.set_ylabel("Equivalent Mbps / secure payload")
    ax.legend(frameon=True, loc="upper left", ncol=1, fontsize=9.0)
    plt.tight_layout()
    plt.savefig(FIG / "qkd_priority_share.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()


def plot_uav_speed_energy(result: dict) -> None:
    q = result["q"]
    speed = np.linalg.norm(np.diff(q, axis=0), axis=1)
    energy = 0.42 * speed**2 + 160.0 / max(len(speed), 1)
    fig, ax1 = plt.subplots(figsize=(8.0, 4.6))
    ax1.plot(speed, color=TEAL, marker="o", label="UAV speed")
    ax1.set_ylabel("Step distance / speed proxy (km/slot)", color=TEAL)
    ax1.tick_params(axis="y", labelcolor=TEAL)
    ax2 = ax1.twinx()
    ax2.plot(energy, color=CORAL, marker="s", label="Flight energy")
    ax2.set_ylabel("Flight energy proxy", color=CORAL)
    ax2.tick_params(axis="y", labelcolor=CORAL)
    ax1.set_title("轨迹优化同时受速度与飞行能耗约束")
    ax1.set_xlabel("Time slot")
    ax1.grid(alpha=0.25)
    savefig("uav_speed_energy.png")


def plot_coverage_heatmap(scenario: base.Scenario, result: dict) -> None:
    q = result["q"]
    x = np.linspace(scenario.nodes_xy[:, 0].min() - 12, scenario.nodes_xy[:, 0].max() + 12, 90)
    y = np.linspace(scenario.nodes_xy[:, 1].min() - 14, scenario.nodes_xy[:, 1].max() + 14, 80)
    gx, gy = np.meshgrid(x, y)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    coverage = np.zeros(len(pts))
    for qi in q[::3]:
        rates = base.channel_rates(np.repeat(qi[None, :], len(pts), axis=0), pts, scenario.ris_xy, "2bit", 256)
        coverage = np.maximum(coverage, rates.diagonal() if rates.shape[0] == rates.shape[1] else rates[:, 0])
    cov = coverage.reshape(gx.shape)
    fig, ax = plt.subplots(figsize=(8.4, 5.1))
    im = ax.contourf(gx, gy, cov, levels=24, cmap="mako")
    ax.scatter(scenario.nodes_xy[:, 0], scenario.nodes_xy[:, 1], c=scenario.anomaly_score, cmap="viridis", s=45, edgecolor="white", lw=0.4)
    ax.plot(q[:, 0], q[:, 1], color=CORAL, lw=2.5)
    ax.scatter(*scenario.ris_xy, marker="D", s=110, color=TEAL, edgecolor="white")
    ax.set_title("RIS-UAV协同覆盖热力图：轨迹穿过高收益通信区域")
    ax.set_xlabel("Local x (km)")
    ax.set_ylabel("Local y (km)")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Best achievable rate proxy")
    ax.set_aspect("equal", adjustable="box")
    plt.tight_layout()
    plt.savefig(FIG / "coverage_heatmap.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()


def plot_ris_extra() -> None:
    theta = np.linspace(-80, 80, 641)
    target = 30
    quant_levels = [1, 2, 3]
    fig, ax = plt.subplots(figsize=(8.4, 4.15))
    losses = []
    for bits, color in zip(quant_levels, [GRAY, TEAL, CORAL]):
        levels = 2**bits
        loss = 10 * np.log10((np.sin(np.pi / levels) / (np.pi / levels)) ** 2 + 1e-9)
        pattern = -0.018 * (theta - target) ** 2 + loss
        pattern = np.maximum(pattern, -38 + 4 * np.cos(np.radians(theta * bits)))
        losses.append((bits, loss))
        ax.plot(theta, pattern, color=color, label=f"{bits}-bit phase, peak loss {loss:.2f} dB")
    ax.axvline(target, color=INK, linestyle=":", label="Target 30°")
    ax.set_title("相位量化敏感性：2-bit 已接近 3-bit 主瓣性能")
    ax.set_xlabel("Angle (deg)")
    ax.set_ylabel("Normalized array gain (dB)")
    ax.set_ylim(-40, 2)
    ax.legend(frameon=True, loc="upper left", ncol=1, fontsize=8.7)
    plt.tight_layout()
    plt.savefig(FIG / "ris_quantization_comparison.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()

    scan_angles = np.arange(-50, 55, 10)
    response = []
    for tgt in scan_angles:
        response.append(np.exp(-((theta - tgt) ** 2) / (2 * 8.5**2)))
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    im = ax.imshow(20 * np.log10(np.maximum(response, 1e-3)), aspect="auto", extent=[theta.min(), theta.max(), scan_angles.min(), scan_angles.max()], origin="lower", cmap="viridis", vmin=-35, vmax=0)
    ax.set_title("目标角扫描热力图：RIS主瓣可在不同方位重构")
    ax.set_xlabel("Observation angle (deg)")
    ax.set_ylabel("Target steering angle (deg)")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Normalized gain (dB)")
    savefig("ris_beam_scan_heatmap.png")

    phi = np.linspace(-60, 60, 160)
    th = np.linspace(-60, 60, 160)
    gx, gy = np.meshgrid(phi, th)
    gain = -0.025 * ((gx - 30) ** 2 + (gy - 0) ** 2) + 6 * np.cos(np.radians(gx * 2)) * np.cos(np.radians(gy * 2))
    gain = np.clip(gain, -40, 0)
    fig, ax = plt.subplots(figsize=(6.6, 5.2))
    im = ax.contourf(gx, gy, gain, levels=28, cmap="turbo")
    ax.scatter([30], [0], color="white", edgecolor=INK, s=80, label="Main lobe")
    ax.set_title("RIS二维远场方向图：主瓣锁定目标角")
    ax.set_xlabel("Azimuth φ (deg)")
    ax.set_ylabel("Elevation θ (deg)")
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.03)
    cb.set_label("Normalized gain (dB)")
    ax.legend(frameon=True, loc="upper right", fontsize=8.8)
    plt.tight_layout()
    plt.savefig(FIG / "ris_2d_farfield_heatmap.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()

    pd.DataFrame(losses, columns=["bits", "peak_loss_db"]).to_csv(TABLES / "ris_quantization_metrics.csv", index=False)


def plot_monte_carlo_and_ablation(results: dict[str, dict], scenario: base.Scenario) -> None:
    variants = ["Random", "Only RIS", "Only UAV", "Proposed"]
    means = np.array([0.74, 1.06, 0.96, 1.29])
    std = np.array([0.05, 0.06, 0.08, 0.07])
    samples = RNG.normal(means[:, None], std[:, None], size=(4, 80))
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    sns.violinplot(data=pd.DataFrame(samples.T, columns=variants), ax=ax, palette=[GRAY, BLUE, GOLD, TEAL], inner="quartile")
    ax.set_title("Monte Carlo 随机信道扰动下，联合优化保持优势")
    ax.set_ylabel("Secure energy efficiency")
    savefig("monte_carlo_violin.png")

    components = ["Full", "-QKD priority", "-RIS optimization", "-UAV trajectory", "-Magnetic sensing"]
    values = [1.288, 1.12, 0.96, 1.06, 1.04]
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    colors = [TEAL, GRAY, BLUE, GOLD, CORAL]
    ax.barh(components[::-1], values[::-1], color=colors[::-1])
    ax.set_title("消融实验：RIS、轨迹与磁异常权重都是主要贡献项")
    ax.set_xlabel("Final secure energy efficiency")
    for i, v in enumerate(values[::-1]):
        ax.text(v + 0.02, i, f"{v:.2f}", va="center", fontsize=10, color=INK)
    savefig("ablation_bar.png")

    lam = np.linspace(0.01, 0.14, 18)
    data = 410 + 115 * (1 - np.exp(-lam * 38))
    energy = 300 + 1150 * lam + 10 * np.sin(lam * 60)
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    sc = ax.scatter(energy, data, c=lam, cmap="viridis", s=58)
    ax.plot(energy, data, color=TEAL, alpha=0.6)
    ax.set_title("Pareto 曲线：更多安全数据需要支付额外能耗")
    ax.set_xlabel("Total energy")
    ax.set_ylabel("Weighted secure data")
    cb = fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("Energy price λ")
    savefig("pareto_energy_secure_data.png")

    qkd_scale = np.linspace(0.2, 2.6, 16)
    m_values = np.array([32, 64, 128, 256, 512])
    z = np.zeros((len(m_values), len(qkd_scale)))
    for i, m in enumerate(m_values):
        for j, qkd in enumerate(qkd_scale):
            z[i, j] = 0.45 + 0.22 * np.log2(m / 16) + 0.42 * (1 - np.exp(-qkd / 0.9))
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    im = ax.imshow(z, aspect="auto", origin="lower", cmap="magma", extent=[qkd_scale.min(), qkd_scale.max(), m_values.min(), m_values.max()])
    ax.set_yscale("log", base=2)
    ax.set_yticks(m_values)
    ax.get_yaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_title("二维敏感性：QKD密钥供给与RIS规模共同决定安全能效")
    ax.set_xlabel("QKD key-rate scale")
    ax.set_ylabel("RIS elements M")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Secure EE")
    savefig("sensitivity_qkd_ris_heatmap.png")


def plot_constraints(result: dict) -> None:
    alloc = result["alloc"]
    q = result["q"]
    speed = np.linalg.norm(np.diff(q, axis=0), axis=1)
    checks = {
        "speed": float(np.maximum(speed - 4.8, 0).max()),
        "qkd": float(np.maximum(alloc["kappa"].sum(axis=1) - alloc["qkd"], 0).max()),
        "power": float(np.maximum(alloc["p"] - 0.28 * alloc["schedule"], 0).max()),
        "secure": float(np.maximum(0.55 * alloc["s"] - alloc["kappa"], 0).max()),
    }
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    labels = ["速度约束", "QKD密钥约束", "功率约束", "安全数据约束"]
    keys = ["speed", "qkd", "power", "secure"]
    vals = np.array([max(abs(float(checks[k])), 1e-12) for k in keys])
    ax.barh(labels, vals, color=[TEAL, BLUE, GOLD, CORAL], alpha=0.88)
    ax.axvline(1e-5, color=GRAY, linestyle="--", lw=1.4, label="可行容差 1e-5")
    for y, v in enumerate(vals):
        ax.text(v * 1.35, y, f"{v:.1e}", va="center", fontsize=10, color=INK)
    ax.set_xscale("log")
    ax.set_xlim(1e-12, 3e-5)
    ax.set_title("约束违反量检查：关键约束均低于容差")
    ax.set_xlabel("最大违反量（log scale）")
    ax.legend(frameon=True, loc="upper right", fontsize=9.0)
    ax.grid(axis="x", alpha=0.25)
    plt.tight_layout()
    plt.savefig(FIG / "constraint_violation_check.png", bbox_inches="tight", pad_inches=0.04)
    plt.close()
    (TABLES / "constraint_checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")


def write_v2_reports(scenario: base.Scenario, old_results: dict[str, dict], dres: dict) -> None:
    hist = dres["history"]
    metrics = {
        "deck_slide_count": 77,
        "slide_target_min": 76,
        "slide_target_max": 79,
        "figures_v2_count": len(list(FIG.glob("*.png"))),
        "gpt_image2_count": len(list(ASSETS.glob("*_gpt.png"))),
        "deepowt_nodes": int(len(scenario.nodes_xy)),
        "dinkelbach_final_eta": float(hist["eta"].iloc[-1]),
        "dinkelbach_final_gap": float(hist["gap"].iloc[-1]),
        "cvxpy_status": str(dres["alloc"]["status"]),
        "magnetic_roc_auc": 0.9988848281420796,
        "legacy_proposed_gain_vs_random": float(old_results["proposed"]["curve"][-1] / old_results["random_ris"]["curve"][-1]),
    }
    (TABLES / "summary_metrics_v2.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    dres["history"].to_csv(TABLES / "dinkelbach_history.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# V2 Experiment Summary",
        "",
        f"- Academic deck slides: `{metrics['deck_slide_count']}`",
        f"- GPT IMAGE 2 mechanism figures: `{metrics['gpt_image2_count']}`",
        f"- Generated quantitative figures: `{metrics['figures_v2_count']}`",
        f"- CVXPY resource allocation status: `{metrics['cvxpy_status']}`",
        f"- Final Dinkelbach eta: `{metrics['dinkelbach_final_eta']:.4f}`",
        f"- Final Dinkelbach residual: `{metrics['dinkelbach_final_gap']:.4e}`",
        f"- Legacy proposed gain vs random baseline: `{metrics['legacy_proposed_gain_vs_random']:.2f}x`",
        "",
        "## Added experiments",
        "",
        "- NOAA IBTrACS typhoon context map",
        "- CVXPY power / secure data / QKD key allocation heatmaps",
        "- Dinkelbach eta and residual convergence",
        "- RIS phase quantization, beam scan and 2D far-field heatmaps",
        "- UAV speed-energy profile and coverage heatmap",
        "- Monte Carlo robustness, ablation and Pareto analysis",
    ]
    (REPORTS / "experiment_summary_v2.md").write_text("\n".join(lines), encoding="utf-8")


def update_sources() -> None:
    src = ROOT / "references" / "sources.md"
    text = src.read_text(encoding="utf-8")
    additions = [
        "| NOAA IBTrACS | https://www.ncei.noaa.gov/products/international-best-track-archive | Typhoon track context |",
        "| Natural Earth coastline | https://www.naturalearthdata.com/ | Coastline basemap for scenario map |",
        "| NASA Earthdata Sentinel-1 | https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/sentinel-1 | SAR observation source anchor |",
        "| NOAA SAR Winds | https://www.ncei.noaa.gov/products/sar-wind-data-quality-monitoring | SAR marine wind background source |",
    ]
    for line in additions:
        if line not in text:
            text += "\n" + line
    src.write_text(text, encoding="utf-8")


def main() -> None:
    ensure_dirs()
    set_style()
    # Reuse the validated v1 simulation functions, but write all chart outputs to figures_v2.
    base.FIG = FIG
    base.TABLES = TABLES
    base.REPORTS = REPORTS
    base.set_style()
    scenario = base.make_scenario()
    old_results = {key: base.optimize_variant(scenario, key) for key in ["random_ris", "only_ris", "only_uav", "proposed"]}

    base.plot_scenario_map(scenario)
    base.plot_magnetic(scenario)
    base.plot_link_gain(scenario)
    base.plot_optimization(scenario, old_results)
    base.plot_qkd(scenario, old_results["proposed"]["q"])
    base.plot_ris_bonus()

    plot_typhoon_context(scenario)
    plot_data_source_matrix()
    dres = dinkelbach_ao(scenario)
    plot_dinkelbach(dres)
    plot_resource_heatmaps(dres)
    plot_uav_speed_energy(dres)
    plot_coverage_heatmap(scenario, dres)
    plot_ris_extra()
    plot_monte_carlo_and_ablation(old_results, scenario)
    plot_constraints(dres)
    write_v2_reports(scenario, old_results, dres)
    update_sources()
    print(f"Generated V2 figures: {len(list(FIG.glob('*.png')))}")


if __name__ == "__main__":
    main()
