% RIS 2-bit phase coding and far-field array-factor reproduction.
% Run in MATLAB 2024a from the project root:
%   run('src/ris_farfield_matlab.m')

clear; clc;
script_dir = fileparts(mfilename('fullpath'));
root_dir = fileparts(script_dir);
out_dir = fullfile(root_dir, 'figures_v2');
if ~exist(out_dir, 'dir')
    mkdir(out_dir);
end

c = 3e8;
fc = 5.8e9;
lambda = c / fc;
d = lambda / 2;
N = 16;
target_theta = 30 * pi/180;
target_phi = 0;
k = 2*pi/lambda;

[mx, my] = meshgrid(0:N-1, 0:N-1);
phase_cont = -k*d*(mx*sin(target_theta)*cos(target_phi) + my*sin(target_theta)*sin(target_phi));
states = [0, pi/2, pi, 3*pi/2];
phase_wrapped = mod(phase_cont, 2*pi);
[~, idx] = min(abs(exp(1j*phase_wrapped(:)) - exp(1j*states)), [], 2);
phase_2bit = reshape(states(idx), N, N);

theta = linspace(-90, 90, 721) * pi/180;
af_cont = zeros(size(theta));
af_2bit = zeros(size(theta));
for t = 1:numel(theta)
    steering = exp(1j*k*d*(mx*sin(theta(t)) + my*0));
    af_cont(t) = abs(sum(exp(1j*phase_cont).*steering, 'all'));
    af_2bit(t) = abs(sum(exp(1j*phase_2bit).*steering, 'all'));
end
af_cont = 20*log10(af_cont/max(af_cont));
af_2bit = 20*log10(af_2bit/max(af_2bit));

figure('Color','w','Position',[100 100 760 620]);
imagesc(rad2deg(phase_2bit)); axis image; colorbar;
title('MATLAB R2024a: 16x16 2-bit RIS phase coding at 5.8 GHz');
xlabel('Element x'); ylabel('Element y');
exportgraphics(gcf, fullfile(out_dir, 'ris_matlab_phase_coding.png'), 'Resolution', 240);
savefig(gcf, fullfile(out_dir, 'ris_matlab_phase_coding.fig'));

figure('Color','w','Position',[120 120 860 560]);
plot(rad2deg(theta), af_cont, 'LineWidth', 2); hold on;
plot(rad2deg(theta), af_2bit, '--', 'LineWidth', 2);
xline(30, ':k', 'LineWidth', 1.2);
text(33, -4.2, 'Target 30 deg', 'FontSize', 12, 'Color', [0.1 0.1 0.1]);
grid on; ylim([-40 1]); xlim([-90 90]);
xlabel('Angle (deg)'); ylabel('Normalized gain (dB)');
legend('Continuous phase', '2-bit phase', 'Location', 'southwest', 'NumColumns', 1);
title('MATLAB R2024a: RIS far-field beam steering');
exportgraphics(gcf, fullfile(out_dir, 'ris_matlab_farfield.png'), 'Resolution', 240);
savefig(gcf, fullfile(out_dir, 'ris_matlab_farfield.fig'));

freq = linspace(5.2, 6.4, 240);
states_deg = [0, 90, 180, 270];
figure('Color','w','Position',[140 140 860 560]);
hold on;
for ii = 1:numel(states_deg)
    slope = -135 * (freq - 5.8);
    ripple = 18 * sin((freq - 5.8) * pi * (1.2 + 0.18 * ii));
    curve = mod(states_deg(ii) + slope + ripple + 540, 360) - 180;
    plot(freq, curve, 'LineWidth', 2);
end
xline(5.8, ':k', '5.8 GHz');
grid on;
xlim([5.2 6.4]); ylim([-190 190]);
xlabel('Frequency (GHz)'); ylabel('Reflection phase S_{11} (deg)');
legend('0 deg state','90 deg state','180 deg state','270 deg state','Location','southwest','NumColumns',1);
title('MATLAB R2024a: RIS unit reflection phase response');
exportgraphics(gcf, fullfile(out_dir, 'ris_matlab_unit_response.png'), 'Resolution', 240);
savefig(gcf, fullfile(out_dir, 'ris_matlab_unit_response.fig'));

fprintf('Saved MATLAB RIS figures to %s\n', out_dir);
