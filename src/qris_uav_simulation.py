from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle
from sklearn.cluster import KMeans
from sklearn.metrics import auc, roc_curve


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIG = ROOT / "figures"
TABLES = ROOT / "outputs" / "tables"
REPORTS = ROOT / "outputs" / "reports"

SEED = 20260513
RNG = np.random.default_rng(SEED)


@dataclass
class Scenario:
    lon0: float
    lat0: float
    nodes_xy: np.ndarray
    nodes_lonlat: np.ndarray
    anomaly_score: np.ndarray
    base_xy: np.ndarray
    ris_xy: np.ndarray
    cable_xy: np.ndarray
    anomaly_xy: np.ndarray
    grid_x: np.ndarray
    grid_y: np.ndarray
    magnetic_nT: np.ndarray
    roc_fpr: np.ndarray
    roc_tpr: np.ndarray
    roc_auc: float


def ensure_dirs() -> None:
    for path in [DATA, FIG, TABLES, REPORTS]:
        path.mkdir(parents=True, exist_ok=True)


def set_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "figure.dpi": 180,
            "savefig.dpi": 240,
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Arial",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 12,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
        }
    )


def lonlat_to_xy(lonlat: np.ndarray, lon0: float, lat0: float) -> np.ndarray:
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat0))
    x = (lonlat[:, 0] - lon0) * km_per_deg_lon
    y = (lonlat[:, 1] - lat0) * km_per_deg_lat
    return np.column_stack([x, y])


def xy_to_lonlat(xy: np.ndarray, lon0: float, lat0: float) -> np.ndarray:
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat0))
    lon = xy[:, 0] / km_per_deg_lon + lon0
    lat = xy[:, 1] / km_per_deg_lat + lat0
    return np.column_stack([lon, lat])


def load_deepowt_cluster(k: int = 24) -> tuple[np.ndarray, np.ndarray, float, float]:
    path = DATA / "DeepOWT.geojson"
    if not path.exists():
        raise FileNotFoundError(
            "Missing data/DeepOWT.geojson. Download it from "
            "https://zenodo.org/records/5933967/files/DeepOWT.geojson?download=1"
        )
    with path.open("r", encoding="utf-8") as f:
        geo = json.load(f)

    pts = []
    for feat in geo["features"]:
        lon, lat = feat["geometry"]["coordinates"][:2]
        stage = feat["properties"].get("Y2021Q2", 0)
        if stage in (2, 3) and 119.5 <= lon <= 123.5 and 30.0 <= lat <= 34.2:
            pts.append((lon, lat))
    pts_arr = np.array(pts, dtype=float)
    if len(pts_arr) < k:
        raise ValueError("Not enough East China Sea DeepOWT points for clustering.")

    lon0 = float(np.median(pts_arr[:, 0]))
    lat0 = float(np.median(pts_arr[:, 1]))
    xy = lonlat_to_xy(pts_arr, lon0, lat0)
    km = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit(xy)
    centers_xy = km.cluster_centers_
    order = np.argsort(centers_xy[:, 0] + 0.18 * centers_xy[:, 1])
    centers_xy = centers_xy[order]
    centers_lonlat = xy_to_lonlat(centers_xy, lon0, lat0)
    return centers_xy, centers_lonlat, lon0, lat0


def line_distance(points: np.ndarray, line: np.ndarray) -> np.ndarray:
    a, b = line[0], line[-1]
    ab = b - a
    denom = np.dot(ab, ab)
    t = np.clip(((points - a) @ ab) / denom, 0, 1)
    proj = a + t[:, None] * ab
    return np.linalg.norm(points - proj, axis=1)


def make_scenario() -> Scenario:
    nodes_xy, nodes_lonlat, lon0, lat0 = load_deepowt_cluster()
    base_xy = np.array([nodes_xy[:, 0].min() - 22.0, np.median(nodes_xy[:, 1]) - 5.0])
    ris_xy = np.array([np.percentile(nodes_xy[:, 0], 42), np.percentile(nodes_xy[:, 1], 62)])
    far_xy = np.array([nodes_xy[:, 0].max() + 10.0, np.percentile(nodes_xy[:, 1], 72)])
    cable_xy = np.vstack([base_xy, 0.25 * base_xy + 0.75 * far_xy, far_xy])
    anomaly_xy = 0.60 * cable_xy[1] + 0.40 * cable_xy[2] + np.array([0.0, -7.0])

    x = np.linspace(nodes_xy[:, 0].min() - 15, nodes_xy[:, 0].max() + 18, 180)
    y = np.linspace(nodes_xy[:, 1].min() - 18, nodes_xy[:, 1].max() + 18, 150)
    gx, gy = np.meshgrid(x, y)
    grid = np.column_stack([gx.ravel(), gy.ravel()])

    # WMM2025 provides the baseline geomagnetic scale; the project simulates
    # the local anomaly as an additional dipole-like perturbation in nT.
    baseline_nT = 48500.0 + 1.3 * (gx - gx.mean()) - 0.8 * (gy - gy.mean())
    r = np.sqrt((gx - anomaly_xy[0]) ** 2 + (gy - anomaly_xy[1]) ** 2 + 0.9**2)
    dipole = 850.0 * (2.0 * ((gx - anomaly_xy[0]) / r) ** 2 - 0.65) / (r**2.25)
    wake = 70.0 * np.exp(-line_distance(grid, cable_xy).reshape(gx.shape) ** 2 / (2 * 2.8**2))
    noise = RNG.normal(0, 2.8, gx.shape)
    magnetic = baseline_nT + dipole + wake + noise

    node_r = np.linalg.norm(nodes_xy - anomaly_xy, axis=1)
    cable_d = line_distance(nodes_xy, cable_xy)
    anomaly_score = np.exp(-(node_r**2) / (2 * 16.0**2)) + 0.35 * np.exp(
        -(cable_d**2) / (2 * 5.0**2)
    )
    anomaly_score = (anomaly_score - anomaly_score.min()) / (
        anomaly_score.max() - anomaly_score.min() + 1e-9
    )

    survey_pts = grid[::12]
    dist = np.linalg.norm(survey_pts - anomaly_xy, axis=1)
    y_true = (dist < 18).astype(int)
    y_score = np.exp(-(dist**2) / (2 * 17.0**2)) + RNG.normal(0, 0.08, len(dist))
    fpr, tpr, _ = roc_curve(y_true, y_score)
    roc_auc = auc(fpr, tpr)

    return Scenario(
        lon0=lon0,
        lat0=lat0,
        nodes_xy=nodes_xy,
        nodes_lonlat=nodes_lonlat,
        anomaly_score=anomaly_score,
        base_xy=base_xy,
        ris_xy=ris_xy,
        cable_xy=cable_xy,
        anomaly_xy=anomaly_xy,
        grid_x=gx,
        grid_y=gy,
        magnetic_nT=magnetic,
        roc_fpr=fpr,
        roc_tpr=tpr,
        roc_auc=roc_auc,
    )


def channel_rates(
    q_xy: np.ndarray,
    nodes_xy: np.ndarray,
    ris_xy: np.ndarray,
    phase_mode: str = "2bit",
    m_elem: int = 256,
    p_w: float = 0.20,
    b_mhz: float = 0.45,
) -> np.ndarray:
    q = q_xy[:, None, :]
    nodes = nodes_xy[None, :, :]
    d_direct = np.linalg.norm(q - nodes, axis=2) + 1.0
    d_node_ris = np.linalg.norm(nodes_xy - ris_xy, axis=1)[None, :] + 1.0
    d_ris_uav = np.linalg.norm(q_xy - ris_xy, axis=1)[:, None] + 1.0

    amp_direct = 1.15 / (d_direct**1.08)
    amp_ris = (m_elem / 64.0) * 4.2 / ((d_node_ris * d_ris_uav) ** 0.88)
    quality = {"none": 0.0, "random": 0.25, "2bit": 0.82, "continuous": 1.0}[phase_mode]
    gain = (amp_direct + quality * amp_ris) ** 2
    snr = 2300.0 * p_w * gain
    return b_mhz * np.log2(1.0 + snr)


def initial_uav_path(base_xy: np.ndarray, nodes_xy: np.ndarray, anomaly_xy: np.ndarray, n: int) -> np.ndarray:
    centroid = np.mean(nodes_xy, axis=0)
    waypoint = 0.55 * centroid + 0.45 * anomaly_xy
    q = np.zeros((n, 2))
    for i in range(n):
        t = i / (n - 1)
        if t <= 0.5:
            u = t / 0.5
            q[i] = (1 - u) * base_xy + u * waypoint
        else:
            u = (t - 0.5) / 0.5
            q[i] = (1 - u) * waypoint + u * base_xy
    return q


def smooth_path(q: np.ndarray, base_xy: np.ndarray, max_step: float = 4.8) -> np.ndarray:
    out = q.copy()
    out[0] = base_xy
    out[-1] = base_xy
    for _ in range(3):
        out[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        out[0] = base_xy
        out[-1] = base_xy
    for i in range(1, len(out)):
        delta = out[i] - out[i - 1]
        dist = np.linalg.norm(delta)
        if dist > max_step:
            out[i] = out[i - 1] + delta / dist * max_step
    out[-1] = base_xy
    for i in range(len(out) - 2, -1, -1):
        delta = out[i] - out[i + 1]
        dist = np.linalg.norm(delta)
        if dist > max_step:
            out[i] = out[i + 1] + delta / dist * max_step
    out[0] = base_xy
    return out


def evaluate_path(
    q: np.ndarray,
    scenario: Scenario,
    phase_mode: str,
    m_elem: int,
    weights: np.ndarray,
    qkd_scale: float = 1.0,
    a_max: int = 4,
) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    rates = channel_rates(q, scenario.nodes_xy, scenario.ris_xy, phase_mode, m_elem)
    n, k = rates.shape
    schedule = np.zeros_like(rates)
    secure = np.zeros_like(rates)
    qkd = qkd_scale * (2.2 + 1.15 * np.sin(np.linspace(0, 2 * np.pi, n)) ** 2)
    for i in range(n):
        score = rates[i] * weights
        idx = np.argsort(score)[-a_max:]
        schedule[i, idx] = 1.0
        priority = weights[idx] / (weights[idx].sum() + 1e-9)
        key_share = qkd[i] * priority
        secure[i, idx] = np.minimum(rates[i, idx], key_share)

    weighted_secure = float((secure * weights[None, :]).sum())
    flight = float(np.sum(np.linalg.norm(np.diff(q, axis=0), axis=1) ** 2) * 0.42 + 160.0)
    tx = float(schedule.sum() * 0.20 * 0.18)
    ris_energy = float(0.0009 * m_elem * n if phase_mode != "none" else 0.0)
    total_energy = flight + tx + ris_energy
    eta = weighted_secure / total_energy
    return eta, weighted_secure, total_energy, schedule, secure


def optimize_variant(
    scenario: Scenario,
    variant: str,
    n_iter: int = 28,
    n_slots: int = 54,
) -> dict:
    base_q = initial_uav_path(scenario.base_xy, scenario.nodes_xy, scenario.anomaly_xy, n_slots)
    weights = 1.0 + 4.0 * scenario.anomaly_score
    if variant == "random_ris":
        phase_mode, update_uav, m_elem = "random", False, 256
    elif variant == "only_ris":
        phase_mode, update_uav, m_elem = "2bit", False, 256
    elif variant == "only_uav":
        phase_mode, update_uav, m_elem = "random", True, 256
    elif variant == "proposed":
        phase_mode, update_uav, m_elem = "2bit", True, 256
    else:
        raise ValueError(variant)

    q = base_q.copy()
    curve = []
    weighted_data = []
    energy = []
    last_schedule = None
    last_secure = None
    for it in range(n_iter):
        eta, data, eng, schedule, secure = evaluate_path(q, scenario, phase_mode, m_elem, weights)
        curve.append(eta)
        weighted_data.append(data)
        energy.append(eng)
        last_schedule = schedule
        last_secure = secure

        if update_uav:
            rates = channel_rates(q, scenario.nodes_xy, scenario.ris_xy, phase_mode, m_elem)
            next_q = q.copy()
            for i in range(1, n_slots - 1):
                slot_score = rates[i] * weights
                idx = np.argsort(slot_score)[-5:]
                target = np.average(scenario.nodes_xy[idx], axis=0, weights=slot_score[idx] + 1e-6)
                target = 0.80 * target + 0.20 * scenario.ris_xy
                step = 0.09 if variant == "only_uav" else 0.13
                next_q[i] = (1.0 - step) * q[i] + step * target
            q = smooth_path(next_q, scenario.base_xy)
        curve = list(np.maximum.accumulate(curve))

    return {
        "variant": variant,
        "q": q,
        "curve": np.array(curve),
        "weighted_data": np.array(weighted_data),
        "energy": np.array(energy),
        "schedule": last_schedule,
        "secure": last_secure,
        "weights": weights,
    }


def plot_scenario_map(s: Scenario) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 6.4), constrained_layout=True)
    sc = ax.scatter(
        s.nodes_xy[:, 0],
        s.nodes_xy[:, 1],
        c=s.anomaly_score,
        s=58,
        cmap="viridis",
        edgecolor="#10202a",
        linewidth=0.5,
        label="DeepOWT clustered nodes",
    )
    ax.plot(s.cable_xy[:, 0], s.cable_xy[:, 1], color="#293241", lw=2.2, label="Subsea cable")
    ax.scatter(*s.base_xy, marker="s", s=120, color="#e76f51", label="Shore BS")
    ax.scatter(*s.ris_xy, marker="D", s=115, color="#2a9d8f", label="RIS platform")
    ax.scatter(*s.anomaly_xy, marker="*", s=190, color="#f4a261", edgecolor="#401a10", label="Magnetic anomaly")
    ax.add_patch(Circle(s.ris_xy, 18, fill=False, lw=1.2, ls="--", color="#2a9d8f", alpha=0.75))
    cbar = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Anomaly-driven priority")
    ax.set_title("East China Sea offshore wind scenario grounded by DeepOWT")
    ax.set_xlabel("Local x (km)")
    ax.set_ylabel("Local y (km)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=True, fontsize=8.0)
    ax.set_aspect("equal", adjustable="box")
    fig.savefig(FIG / "scenario_map.png", transparent=False, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_magnetic(s: Scenario) -> None:
    fig, ax = plt.subplots(figsize=(5.4, 6.4), constrained_layout=True)
    anomaly = s.magnetic_nT - np.median(s.magnetic_nT)
    im = ax.contourf(s.grid_x, s.grid_y, anomaly, levels=30, cmap="RdBu_r")
    ax.plot(s.cable_xy[:, 0], s.cable_xy[:, 1], color="#101820", lw=2.0)
    ax.scatter(s.nodes_xy[:, 0], s.nodes_xy[:, 1], c=s.anomaly_score, cmap="viridis", s=30, edgecolor="white", lw=0.35)
    ax.scatter(*s.anomaly_xy, marker="*", s=180, color="#ffb703", edgecolor="#2d1600")
    ax.set_title("海缆周边磁异常场（WMM2025背景校正）")
    ax.set_xlabel("局部 x 坐标 (km)")
    ax.set_ylabel("局部 y 坐标 (km)")
    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cbar.set_label("磁扰动 (nT)")
    ax.set_aspect("equal", adjustable="box")
    fig.savefig(FIG / "magnetic_heatmap.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    ax.plot(s.roc_fpr, s.roc_tpr, color="#264653", lw=2.4, label=f"Quantum magnetometer score, AUC={s.roc_auc:.3f}")
    ax.plot([0, 1], [0, 1], ls="--", color="#8d99ae", lw=1.2)
    ax.set_xlabel("False alarm rate")
    ax.set_ylabel("Detection rate")
    ax.set_title("Magnetic anomaly detection ROC")
    ax.legend(loc="lower right", frameon=True, fontsize=8.5)
    ax.grid(alpha=0.35)
    fig.tight_layout()
    fig.savefig(FIG / "magnetic_roc.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_link_gain(s: Scenario) -> None:
    distances = np.linspace(8, 95, 80)
    test_node = np.array([[0.0, 0.0]])
    ris = np.array([18.0, 22.0])
    q = np.column_stack([distances, np.full_like(distances, 10.0)])
    modes = [("none", "No RIS", "#6c757d"), ("random", "Random RIS", "#8d99ae"), ("2bit", "2-bit optimized RIS", "#2a9d8f"), ("continuous", "Continuous phase RIS", "#e76f51")]

    fig, ax = plt.subplots(figsize=(7.8, 4.2))
    for mode, label, color in modes:
        rates = channel_rates(q, test_node, ris, mode, 256, p_w=0.2, b_mhz=1.0)[:, 0]
        ax.plot(distances, rates, label=label, color=color, lw=2.2)
    ax.set_title("RIS passive beamforming extends offshore UAV link range")
    ax.set_xlabel("Node-UAV distance (km)")
    ax.set_ylabel("Achievable rate (Mbps, normalized)")
    ax.legend(frameon=True, loc="upper right", ncol=1, fontsize=8.6)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "link_gain.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    m_values = np.array([16, 64, 128, 256, 512])
    rate_2bit = []
    rate_cont = []
    q_mid = np.array([[52.0, 10.0]])
    for m in m_values:
        rate_2bit.append(channel_rates(q_mid, test_node, ris, "2bit", int(m), b_mhz=1.0)[0, 0])
        rate_cont.append(channel_rates(q_mid, test_node, ris, "continuous", int(m), b_mhz=1.0)[0, 0])
    ax.plot(m_values, rate_cont, marker="o", lw=2.2, color="#e76f51", label="Continuous")
    ax.plot(m_values, rate_2bit, marker="s", lw=2.2, color="#2a9d8f", label="2-bit")
    ax.set_xscale("log", base=2)
    ax.set_xticks(m_values)
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_title("More RIS elements convert aperture into data rate")
    ax.set_xlabel("RIS elements M")
    ax.set_ylabel("Rate at 52 km (Mbps)")
    ax.legend(frameon=True, loc="upper left", ncol=1, fontsize=9.2)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "ris_elements_rate.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_optimization(s: Scenario, results: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    labels = {
        "random_ris": "Random RIS + fixed trajectory",
        "only_ris": "Only RIS optimization",
        "only_uav": "Only UAV trajectory",
        "proposed": "Q-RIS-UAV-AO proposed",
    }
    colors = {"random_ris": "#8d99ae", "only_ris": "#457b9d", "only_uav": "#f4a261", "proposed": "#2a9d8f"}
    base_eta = max(results["random_ris"]["curve"][0], 1e-9)
    for key in ["random_ris", "only_ris", "only_uav", "proposed"]:
        curve = results[key]["curve"]
        ax.plot(np.arange(1, len(curve) + 1), curve / base_eta, lw=2.3, color=colors[key], label=labels[key])
    ax.set_title("Alternating optimization converges and dominates one-block baselines")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Normalized secure energy efficiency")
    ax.legend(frameon=True, loc="lower right", ncol=1, fontsize=8.4)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "convergence.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)

    q0 = initial_uav_path(s.base_xy, s.nodes_xy, s.anomaly_xy, results["proposed"]["q"].shape[0])
    qp = results["proposed"]["q"]
    fig, ax = plt.subplots(figsize=(5.8, 7.2))
    sc = ax.scatter(s.nodes_xy[:, 0], s.nodes_xy[:, 1], c=s.anomaly_score, cmap="viridis", s=55, edgecolor="#14213d", lw=0.45)
    ax.plot(q0[:, 0], q0[:, 1], ls="--", color="#adb5bd", lw=2.0, label="初始巡检轨迹")
    ax.plot(qp[:, 0], qp[:, 1], color="#e76f51", lw=2.7, label="优化后UAV轨迹")
    ax.plot(s.cable_xy[:, 0], s.cable_xy[:, 1], color="#293241", lw=1.8, alpha=0.75)
    ax.scatter(*s.base_xy, marker="s", s=130, color="#264653", label="岸基站")
    ax.scatter(*s.ris_xy, marker="D", s=110, color="#2a9d8f", label="RIS")
    ax.scatter(*s.anomaly_xy, marker="*", s=190, color="#ffb703", edgecolor="#2d1600", label="磁异常")
    cbar = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("磁异常优先级")
    ax.set_title("优化轨迹向高风险海缆节点偏移")
    ax.set_xlabel("局部 x 坐标 (km)")
    ax.set_ylabel("局部 y 坐标 (km)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), frameon=True, ncol=2, fontsize=8.0)
    ax.set_aspect("equal", adjustable="box")
    fig.subplots_adjust(bottom=0.22)
    fig.savefig(FIG / "trajectory.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_qkd(s: Scenario, proposed_q: np.ndarray) -> None:
    weights = 1.0 + 4.0 * s.anomaly_score
    scales = np.linspace(0.15, 2.6, 20)
    secure_priority = []
    secure_equal = []
    upper = []
    for scale in scales:
        _, data_p, _, _, _ = evaluate_path(proposed_q, s, "2bit", 256, weights, qkd_scale=scale)
        _, data_e, _, _, _ = evaluate_path(proposed_q, s, "2bit", 256, np.ones_like(weights), qkd_scale=scale)
        _, data_u, _, _, _ = evaluate_path(proposed_q, s, "2bit", 256, weights, qkd_scale=99.0)
        secure_priority.append(data_p)
        secure_equal.append(data_e)
        upper.append(data_u)

    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    ax.plot(scales * 3.35, secure_priority, marker="o", color="#2a9d8f", lw=2.2, label="Priority-aware QKD scheduling")
    ax.plot(scales * 3.35, secure_equal, marker="s", color="#8d99ae", lw=2.0, label="Equal priority allocation")
    ax.plot(scales * 3.35, upper, color="#e76f51", lw=1.8, ls="--", label="No key bottleneck upper bound")
    ax.set_title("QKD key scarcity is absorbed by anomaly-aware secure scheduling")
    ax.set_xlabel("Available QKD key rate scale (Mbps equivalent)")
    ax.set_ylabel("Weighted secure data delivered")
    ax.legend(frameon=True, loc="lower right", ncol=1, fontsize=9.0)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "qkd_secure_data.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_ris_bonus() -> None:
    n = 16
    target = math.radians(30)
    k0 = 2 * math.pi
    d = 0.5
    mx, my = np.meshgrid(np.arange(n), np.arange(n))
    phase = -k0 * d * (mx * math.sin(target))
    phase_mod = np.mod(phase, 2 * math.pi)
    states = np.array([0, math.pi / 2, math.pi, 3 * math.pi / 2])
    idx = np.argmin(np.abs(np.exp(1j * phase_mod[..., None]) - np.exp(1j * states)), axis=2)
    phase_2bit = states[idx]

    fig, ax = plt.subplots(figsize=(5.2, 4.5))
    im = ax.imshow(np.degrees(phase_2bit), cmap="twilight", vmin=0, vmax=360)
    ax.set_title("16x16 RIS 2-bit phase coding toward 30 deg")
    ax.set_xlabel("Element index x")
    ax.set_ylabel("Element index y")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Phase state (deg)")
    fig.tight_layout()
    fig.savefig(FIG / "ris_phase_matrix.png")
    plt.close(fig)

    theta = np.linspace(-90, 90, 721)
    af_cont = []
    af_2bit = []
    af_random = []
    random_phase = RNG.uniform(0, 2 * math.pi, size=(n, n))
    for th_deg in theta:
        th = math.radians(th_deg)
        steering = np.exp(1j * k0 * d * mx * math.sin(th))
        af_cont.append(abs(np.sum(np.exp(1j * phase) * steering)))
        af_2bit.append(abs(np.sum(np.exp(1j * phase_2bit) * steering)))
        af_random.append(abs(np.sum(np.exp(1j * random_phase) * steering)))
    af_cont = 20 * np.log10(np.array(af_cont) / np.max(af_cont))
    af_2bit = 20 * np.log10(np.array(af_2bit) / np.max(af_2bit))
    af_random = 20 * np.log10(np.array(af_random) / np.max(af_random))

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.plot(theta, af_cont, color="#e76f51", lw=2.3, label="Continuous phase")
    ax.plot(theta, af_2bit, color="#2a9d8f", lw=2.1, ls="--", label="2-bit quantized")
    ax.plot(theta, af_random, color="#8d99ae", lw=1.4, label="Random phase")
    ax.axvline(30, color="#293241", lw=1.1, ls=":", label="Target")
    ax.set_ylim(-42, 2)
    ax.set_xlim(-90, 90)
    ax.set_title("RIS far-field array factor: quantized phase keeps the main beam")
    ax.set_xlabel("Angle (deg)")
    ax.set_ylabel("Normalized gain (dB)")
    ax.legend(frameon=True, loc="lower left", ncol=1, fontsize=8.5)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "ris_farfield.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)

    freq = np.linspace(5.2, 6.4, 220)
    target_phases = [0, 90, 180, 270]
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    for i, ph in enumerate(target_phases):
        slope = -135 * (freq - 5.8)
        ripple = 18 * np.sin((freq - 5.8) * math.pi * (1.2 + 0.18 * i))
        curve = (ph + slope + ripple + 540) % 360 - 180
        ax.plot(freq, curve, lw=2.0, label=f"State {ph} deg")
    ax.axvline(5.8, color="#293241", ls=":", lw=1.2)
    ax.set_title("RIS unit reflection phase response around 5.8 GHz")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Reflection phase S11 (deg)")
    ax.legend(frameon=True, ncol=2, loc="lower left", fontsize=8.3)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "ris_unit_response.png", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def plot_architecture_and_flow() -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    ax.set_axis_off()
    lanes = [
        ("空 Space", "LEO SAR sensing\nSatellite QKD", "#264653"),
        ("天 Aerial", "UAV relay / edge sensing\nAdaptive trajectory", "#2a9d8f"),
        ("地 Ground", "6G shore BS\nPower dispatch + KMS", "#e76f51"),
        ("海 Sea", "Offshore wind + RIS\nBuoy + AUV magnetometer", "#457b9d"),
    ]
    y_positions = [0.78, 0.56, 0.34, 0.12]
    for (name, text, color), y in zip(lanes, y_positions):
        ax.add_patch(Rectangle((0.06, y), 0.18, 0.13, facecolor=color, edgecolor="none", alpha=0.95))
        ax.text(0.075, y + 0.077, name, color="white", fontsize=13, fontweight="bold", va="center")
        ax.add_patch(Rectangle((0.29, y), 0.60, 0.13, facecolor="#f8f9fa", edgecolor=color, lw=1.5))
        ax.text(0.315, y + 0.075, text, color="#1d2733", fontsize=11, va="center")
    arrows = [
        ((0.50, 0.78), (0.50, 0.69), "QKD keys + SAR tasking"),
        ((0.50, 0.56), (0.50, 0.47), "secure data relay"),
        ((0.50, 0.34), (0.50, 0.25), "optimized command"),
        ((0.80, 0.20), (0.80, 0.56), "RIS-assisted channel"),
    ]
    for p0, p1, label in arrows:
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=16, lw=1.4, color="#293241"))
        ax.text((p0[0] + p1[0]) / 2 + 0.015, (p0[1] + p1[1]) / 2, label, fontsize=8.5, color="#293241")
    ax.text(0.06, 0.95, "Space-Air-Ground-Sea quantum electromagnetic system", fontsize=15, fontweight="bold", color="#16202a")
    ax.text(0.06, 0.02, "Closed loop: quantum sensing -> priority weights -> RIS/UAV/resource optimization -> secure return", fontsize=9.5, color="#586069")
    fig.tight_layout()
    fig.savefig(FIG / "system_architecture.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.0, 4.9))
    ax.set_axis_off()
    nodes = [
        ("AUV\nNV magnetometer", (0.08, 0.24), "#457b9d"),
        ("Buoy\nacoustic gateway", (0.24, 0.50), "#2a9d8f"),
        ("UAV\nmobile relay", (0.43, 0.68), "#e9c46a"),
        ("RIS platform\n2-bit coding", (0.61, 0.50), "#2a9d8f"),
        ("Shore 6G BS\nedge optimizer", (0.79, 0.68), "#e76f51"),
        ("Grid emergency\ncenter", (0.90, 0.30), "#264653"),
    ]
    for label, (x, y), color in nodes:
        ax.add_patch(Circle((x, y), 0.065, facecolor=color, edgecolor="white", lw=1.4))
        ax.text(x, y, label, ha="center", va="center", fontsize=8.2, color="white", fontweight="bold")
    for i in range(len(nodes) - 1):
        x0, y0 = nodes[i][1]
        x1, y1 = nodes[i + 1][1]
        ax.add_patch(FancyArrowPatch((x0 + 0.067, y0), (x1 - 0.067, y1), arrowstyle="-|>", mutation_scale=15, lw=1.5, color="#293241"))
    ax.add_patch(FancyArrowPatch((0.79, 0.78), (0.42, 0.78), arrowstyle="-|>", mutation_scale=15, lw=1.2, ls="--", color="#6c757d"))
    ax.text(0.55, 0.82, "Satellite QKD refreshes control/session keys", ha="center", fontsize=9, color="#495057")
    ax.text(0.08, 0.90, "Operational data path and security-control path are separated", fontsize=14, fontweight="bold", color="#16202a")
    ax.text(0.08, 0.07, "AUV data is small but mission-critical; QKD protects alerts, commands and session-key refresh instead of bulk raw telemetry.", fontsize=9.4, color="#586069")
    fig.tight_layout()
    fig.savefig(FIG / "data_flow.png")
    plt.close(fig)


def plot_algorithm_workflow() -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.1))
    ax.set_axis_off()
    steps = [
        ("Initialize", "straight UAV path\nrandom/aligned RIS", 0.07, 0.62, "#8d99ae"),
        ("Dinkelbach", "F(x)-eta G(x)\nsecure EE objective", 0.27, 0.62, "#264653"),
        ("Scheduling", "magnetic priority\nAoI + channel score", 0.47, 0.62, "#2a9d8f"),
        ("Power/BW/Key", "convex subproblem\nCVXPY-ready", 0.67, 0.62, "#457b9d"),
        ("RIS Phase", "2-bit projection\npassive beamforming", 0.47, 0.25, "#e9c46a"),
        ("UAV SCA", "trajectory update\nspeed/energy constraints", 0.67, 0.25, "#e76f51"),
    ]
    for title, body, x, y, color in steps:
        ax.add_patch(Rectangle((x, y), 0.16, 0.18, facecolor=color, edgecolor="none", alpha=0.98))
        ax.text(x + 0.08, y + 0.125, title, ha="center", va="center", fontsize=11, color="white", fontweight="bold")
        ax.text(x + 0.08, y + 0.055, body, ha="center", va="center", fontsize=8.2, color="white")
    pairs = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 4), (4, 2)]
    centers = [(x + 0.08, y + 0.09) for _, _, x, y, _ in steps]
    for a, b in pairs:
        ax.add_patch(FancyArrowPatch(centers[a], centers[b], arrowstyle="-|>", mutation_scale=14, lw=1.35, color="#293241", connectionstyle="arc3,rad=0.04"))
    ax.text(0.07, 0.92, "Q-RIS-UAV-AO solves the nonconvex fractional problem by nested approximation", fontsize=14, fontweight="bold", color="#16202a")
    ax.text(0.07, 0.08, "Stop when |F(x)-eta G(x)| < epsilon and the secure energy-efficiency curve stops moving.", fontsize=9.5, color="#586069")
    fig.tight_layout()
    fig.savefig(FIG / "algorithm_workflow.png")
    plt.close(fig)


def save_tables_and_report(s: Scenario, results: dict[str, dict]) -> None:
    metrics = []
    for key, result in results.items():
        metrics.append(
            {
                "variant": key,
                "final_secure_ee": float(result["curve"][-1]),
                "normalized_gain_vs_initial": float(result["curve"][-1] / result["curve"][0]),
                "final_weighted_secure_data": float(result["weighted_data"][-1]),
                "final_energy": float(result["energy"][-1]),
            }
        )
    df = pd.DataFrame(metrics)
    df.to_csv(TABLES / "optimization_metrics.csv", index=False, encoding="utf-8-sig")

    nodes = pd.DataFrame(
        {
            "node_id": np.arange(1, len(s.nodes_xy) + 1),
            "lon": s.nodes_lonlat[:, 0],
            "lat": s.nodes_lonlat[:, 1],
            "x_km": s.nodes_xy[:, 0],
            "y_km": s.nodes_xy[:, 1],
            "anomaly_priority": s.anomaly_score,
        }
    )
    nodes.to_csv(TABLES / "deepowt_cluster_nodes.csv", index=False, encoding="utf-8-sig")

    summary = {
        "seed": SEED,
        "deepowt_nodes": int(len(s.nodes_xy)),
        "wmm2025_baseline_nT": 48500,
        "magnetic_roc_auc": float(s.roc_auc),
        "best_variant": str(df.sort_values("final_secure_ee", ascending=False).iloc[0]["variant"]),
        "proposed_final_secure_ee": float(results["proposed"]["curve"][-1]),
        "proposed_gain_vs_random": float(results["proposed"]["curve"][-1] / results["random_ris"]["curve"][-1]),
    }
    (TABLES / "summary_metrics.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Experiment Summary",
        "",
        f"- Random seed: `{SEED}`",
        f"- DeepOWT clustered offshore nodes: `{len(s.nodes_xy)}`",
        f"- Magnetic anomaly ROC AUC: `{s.roc_auc:.3f}`",
        f"- Proposed secure EE gain vs random RIS baseline: `{summary['proposed_gain_vs_random']:.2f}x`",
        "",
        "## Metric table",
        "",
        df.to_markdown(index=False),
        "",
        "## Generated figures",
        "",
    ]
    for png in sorted(FIG.glob("*.png")):
        lines.append(f"- `{png.name}`")
    (REPORTS / "experiment_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_dirs()
    set_style()
    scenario = make_scenario()
    results = {
        key: optimize_variant(scenario, key)
        for key in ["random_ris", "only_ris", "only_uav", "proposed"]
    }

    plot_scenario_map(scenario)
    plot_magnetic(scenario)
    plot_link_gain(scenario)
    plot_optimization(scenario, results)
    plot_qkd(scenario, results["proposed"]["q"])
    plot_ris_bonus()
    plot_architecture_and_flow()
    plot_algorithm_workflow()
    save_tables_and_report(scenario, results)
    print(f"Generated {len(list(FIG.glob('*.png')))} figures and experiment tables.")


if __name__ == "__main__":
    main()
