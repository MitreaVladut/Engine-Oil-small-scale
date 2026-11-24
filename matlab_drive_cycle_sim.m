%% matlab_drive_cycle_sim.m
% Algorithmic Engine Oil Life Monitoring System - Vehicle Telemetry Simulator
% Student: MITREA VLADUT-CRISTIAN | Supervisor: CONSTANTIN-RENATO IVANESCU
% Faculty of Automation, Computers and Electronics
% Target: 2004 Skoda Fabia 1.4L (ISO 9141-2 OBD-II testbed)
%
% This script models vehicle speed, crankshaft RPM, engine load, and coolant
% temperature thermal dynamics. It exports synthetic telemetry matching the
% exact schema of 'car_telemetry_log.csv'.

clear; clc;

fprintf('=====================================================\n');
fprintf(' Skoda Fabia 1.4L - Drive Cycle Simulator (MATLAB)   \n');
fprintf('=====================================================\n');

%% 1. Simulation Parameters
dt = 1.0;                 % Time step (seconds)
duration = 600;           % 10-minute cycle (seconds)
time_vec = (0:dt:(duration - dt))';
N = length(time_vec);

% Select Scenario: 'cold_short_trip', 'steady_highway', or 'aggressive'
scenario = 'cold_short_trip'; 
ambient_temp = 20.0;      % Deg C

%% 2. Pre-allocate Telemetry Vectors
RPM = zeros(N, 1);
Speed_KMH = zeros(N, 1);
Coolant_Temp_C = zeros(N, 1);
Engine_Load_Pct = zeros(N, 1);

%% 3. Dynamic Cycle Generation
current_temp = ambient_temp;
if strcmp(scenario, 'steady_highway')
    current_temp = 89.5; % Pre-warmed
end

for i = 1:N
    t = time_vec(i);
    
    switch scenario
        case 'cold_short_trip'
            % Urban stop-and-go (90s period)
            phase = mod(t, 90);
            if phase < 20
                % Idle
                Speed_KMH(i) = 0.0;
                RPM(i) = 780 + 15 * sin(t * 0.5);
                Engine_Load_Pct(i) = 4.0 + 2.0 * sin(t * 0.2);
            elseif phase < 45
                % Accelerate 0 - 42 km/h
                accel_t = (phase - 20) / 25.0;
                Speed_KMH(i) = 42.0 * sin(accel_t * pi / 2);
                RPM(i) = 1800 + 1200 * accel_t;
                Engine_Load_Pct(i) = 45.0 + 25.0 * accel_t;
            elseif phase < 75
                % Cruising 38 km/h
                Speed_KMH(i) = 38.0 + 4.0 * sin(t * 0.3);
                RPM(i) = 2100 + 100 * sin(t * 0.3);
                Engine_Load_Pct(i) = 22.0 + 5.0 * sin(t * 0.2);
            else
                % Decelerate
                decel_t = (90 - phase) / 15.0;
                Speed_KMH(i) = 38.0 * decel_t;
                RPM(i) = 1200 * decel_t + 780;
                Engine_Load_Pct(i) = 3.0;
            end
            
        case 'steady_highway'
            Speed_KMH(i) = 98.0 + 6.0 * sin(t * 0.05);
            RPM(i) = 2650 + 150 * sin(t * 0.05);
            Engine_Load_Pct(i) = 22.0 + 4.0 * sin(t * 0.08);
            
        case 'aggressive'
            phase = mod(t, 40);
            if phase < 25
                norm_p = phase / 25.0;
                RPM(i) = 3400 + 2000 * norm_p;
                Engine_Load_Pct(i) = 65.0 + 30.0 * norm_p;
                Speed_KMH(i) = 60.0 + 70.0 * norm_p;
            else
                RPM(i) = 3800 - 1500 * ((phase - 25) / 15.0);
                Engine_Load_Pct(i) = 15.0;
                Speed_KMH(i) = 100.0 - 20.0 * ((phase - 25) / 15.0);
            end
    end
    
    % Lumped Coolant Thermal Integration
    heat_gen = (RPM(i) / 3000.0) * (Engine_Load_Pct(i) / 100.0) * 1.8;
    cooling = 0.015 + (Speed_KMH(i) / 120.0) * 0.02;
    if current_temp < 85.0
        dT = (heat_gen * 2.2 - (current_temp - ambient_temp) * 0.008) * dt;
    else
        dT = (heat_gen * 1.0 - (current_temp - 90.0) * cooling) * dt;
    end
    current_temp = max(ambient_temp, min(115.0, current_temp + dT));
    Coolant_Temp_C(i) = round(current_temp, 1);
    
    RPM(i) = round(RPM(i));
    Speed_KMH(i) = round(Speed_KMH(i), 1);
    Engine_Load_Pct(i) = round(Engine_Load_Pct(i), 2);
end

%% 4. Format Timestamps and Export Table
base_date = datetime('now');
timestamps = strings(N, 1);
for i = 1:N
    cur_dt = base_date + seconds(time_vec(i));
    timestamps(i) = datestr(cur_dt, 'yyyy-mm-dd HH:MM:SS');
end

% Construct Table matching OBD logger CSV schema
TelemetryTable = table(timestamps, RPM, Speed_KMH, Coolant_Temp_C, Engine_Load_Pct, ...
    'VariableNames', {'Timestamp', 'RPM', 'Speed_KMH', 'Coolant_Temp_C', 'Engine_Load_Pct'});

output_filename = sprintf('matlab_telemetry_%s.csv', scenario);
writetable(TelemetryTable, output_filename);
fprintf('[+] Successfully generated and exported %d rows to: %s\n', N, output_filename);
