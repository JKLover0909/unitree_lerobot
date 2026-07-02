#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

namespace {

using LowState = unitree_hg::msg::dds_::LowState_;

constexpr int kMotorDof = 29;
constexpr const char* kLowStateTopic = "rt/lowstate";

std::atomic<bool> g_running{true};

struct Options {
  std::string network_interface;
  std::string output_csv = "g1_lowstate.csv";
  double frequency = 30.0;
  double duration_s = 0.0;  // 0 means until Ctrl+C.
  double state_timeout_s = 5.0;
  int print_every = 100;
};

struct StateSnapshot {
  std::chrono::steady_clock::time_point steady_time;
  double wall_time_s = 0.0;
  uint8_t mode_machine = 0;
  uint32_t tick = 0;
  float q[kMotorDof]{};
  float dq[kMotorDof]{};
  float tau_est[kMotorDof]{};
  float imu_quat[4]{};
  float imu_omega[3]{};
  float imu_accel[3]{};
};

std::mutex g_state_mutex;
std::optional<StateSnapshot> g_latest_state;

void SignalHandler(int) {
  g_running = false;
}

bool StartsWith(const std::string& s, const std::string& prefix) {
  return s.rfind(prefix, 0) == 0;
}

std::string ValueForArg(int& i, int argc, char** argv, const std::string& arg) {
  const std::string prefix = arg + "=";
  const std::string current = argv[i];
  if (StartsWith(current, prefix)) {
    return current.substr(prefix.size());
  }
  if (i + 1 >= argc) {
    throw std::runtime_error("Missing value for " + arg);
  }
  return argv[++i];
}

Options ParseArgs(int argc, char** argv) {
  Options opt;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--help" || arg == "-h") {
      std::cout
          << "Usage: " << argv[0] << " [options]\n\n"
          << "Options:\n"
          << "  --network-interface IFACE   DDS interface, e.g. eth0 or enp1s0\n"
          << "  --output-csv PATH           output CSV, default g1_lowstate.csv\n"
          << "  --frequency HZ              sample/write frequency, default 30\n"
          << "  --duration-s SEC            stop after seconds, 0 means Ctrl+C\n"
          << "  --state-timeout-s SEC       max lowstate age, default 5\n"
          << "  --print-every N             progress print interval, default 100\n";
      std::exit(0);
    } else if (arg == "--network-interface" || StartsWith(arg, "--network-interface=")) {
      opt.network_interface = ValueForArg(i, argc, argv, "--network-interface");
    } else if (arg == "--output-csv" || StartsWith(arg, "--output-csv=")) {
      opt.output_csv = ValueForArg(i, argc, argv, "--output-csv");
    } else if (arg == "--frequency" || StartsWith(arg, "--frequency=")) {
      opt.frequency = std::stod(ValueForArg(i, argc, argv, "--frequency"));
    } else if (arg == "--duration-s" || StartsWith(arg, "--duration-s=")) {
      opt.duration_s = std::stod(ValueForArg(i, argc, argv, "--duration-s"));
    } else if (arg == "--state-timeout-s" || StartsWith(arg, "--state-timeout-s=")) {
      opt.state_timeout_s = std::stod(ValueForArg(i, argc, argv, "--state-timeout-s"));
    } else if (arg == "--print-every" || StartsWith(arg, "--print-every=")) {
      opt.print_every = std::stoi(ValueForArg(i, argc, argv, "--print-every"));
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }
  if (opt.frequency <= 0 || opt.duration_s < 0 || opt.state_timeout_s <= 0 || opt.print_every <= 0) {
    throw std::runtime_error("frequency/state-timeout/print-every must be positive; duration must be non-negative");
  }
  return opt;
}

double WallTimeSeconds() {
  using namespace std::chrono;
  return duration<double>(system_clock::now().time_since_epoch()).count();
}

void LowStateHandler(const void* message) {
  const auto* low_state = static_cast<const LowState*>(message);
  StateSnapshot state;
  state.steady_time = std::chrono::steady_clock::now();
  state.wall_time_s = WallTimeSeconds();
  state.mode_machine = low_state->mode_machine();
  state.tick = low_state->tick();

  for (int i = 0; i < kMotorDof; ++i) {
    state.q[i] = low_state->motor_state().at(i).q();
    state.dq[i] = low_state->motor_state().at(i).dq();
    state.tau_est[i] = low_state->motor_state().at(i).tau_est();
  }
  for (int i = 0; i < 4; ++i) {
    state.imu_quat[i] = low_state->imu_state().quaternion().at(i);
  }
  for (int i = 0; i < 3; ++i) {
    state.imu_omega[i] = low_state->imu_state().gyroscope().at(i);
    state.imu_accel[i] = low_state->imu_state().accelerometer().at(i);
  }

  std::lock_guard<std::mutex> lock(g_state_mutex);
  g_latest_state = state;
}

StateSnapshot WaitLatestState(double timeout_s) {
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(timeout_s);
  while (std::chrono::steady_clock::now() < deadline && g_running) {
    {
      std::lock_guard<std::mutex> lock(g_state_mutex);
      if (g_latest_state.has_value()) {
        return *g_latest_state;
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  throw std::runtime_error("No rt/lowstate received within timeout");
}

StateSnapshot GetFreshState(double max_age_s) {
  std::lock_guard<std::mutex> lock(g_state_mutex);
  if (!g_latest_state.has_value()) {
    throw std::runtime_error("No rt/lowstate received yet");
  }
  const double age = std::chrono::duration<double>(std::chrono::steady_clock::now() - g_latest_state->steady_time).count();
  if (age > max_age_s) {
    throw std::runtime_error("rt/lowstate is stale; age=" + std::to_string(age));
  }
  return *g_latest_state;
}

void WriteHeader(std::ofstream& out) {
  out << "sample_index,wall_time_s,elapsed_s,tick,mode_machine";
  for (int i = 0; i < kMotorDof; ++i) out << ",q" << i;
  for (int i = 0; i < kMotorDof; ++i) out << ",dq" << i;
  for (int i = 0; i < kMotorDof; ++i) out << ",tau_est" << i;
  for (int i = 0; i < 4; ++i) out << ",imu_quat" << i;
  for (int i = 0; i < 3; ++i) out << ",imu_omega" << i;
  for (int i = 0; i < 3; ++i) out << ",imu_accel" << i;
  out << "\n";
}

void WriteRow(std::ofstream& out, uint64_t sample_index, const StateSnapshot& state, double elapsed_s) {
  out << sample_index << "," << std::fixed << std::setprecision(9)
      << state.wall_time_s << "," << elapsed_s << ","
      << state.tick << "," << unsigned(state.mode_machine);
  out << std::setprecision(7);
  for (int i = 0; i < kMotorDof; ++i) out << "," << state.q[i];
  for (int i = 0; i < kMotorDof; ++i) out << "," << state.dq[i];
  for (int i = 0; i < kMotorDof; ++i) out << "," << state.tau_est[i];
  for (int i = 0; i < 4; ++i) out << "," << state.imu_quat[i];
  for (int i = 0; i < 3; ++i) out << "," << state.imu_omega[i];
  for (int i = 0; i < 3; ++i) out << "," << state.imu_accel[i];
  out << "\n";
}

void PrintJointMapping() {
  std::cout
      << "G1 29DoF joint index mapping:\n"
      << "  0..5   left leg\n"
      << "  6..11  right leg\n"
      << "  12..14 waist\n"
      << "  15..21 left arm\n"
      << "  22..28 right arm\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options opt = ParseArgs(argc, argv);
    std::signal(SIGINT, SignalHandler);
    std::signal(SIGTERM, SignalHandler);

    if (opt.network_interface.empty()) {
      unitree::robot::ChannelFactory::Instance()->Init(0);
    } else {
      unitree::robot::ChannelFactory::Instance()->Init(0, opt.network_interface);
    }

    unitree::robot::ChannelSubscriber<LowState> subscriber(kLowStateTopic);
    subscriber.InitChannel(LowStateHandler, 10);

    PrintJointMapping();
    std::cout << "Waiting for " << kLowStateTopic << " on interface "
              << (opt.network_interface.empty() ? "<default>" : opt.network_interface) << "...\n";
    const auto first = WaitLatestState(opt.state_timeout_s);
    std::cout << "First state received: mode_machine=" << unsigned(first.mode_machine)
              << " tick=" << first.tick << "\n";

    std::ofstream out(opt.output_csv);
    if (!out) {
      throw std::runtime_error("Could not open output CSV: " + opt.output_csv);
    }
    WriteHeader(out);

    const auto start = std::chrono::steady_clock::now();
    const auto period = std::chrono::duration<double>(1.0 / opt.frequency);
    auto next_tick = start;
    uint64_t sample_index = 0;

    std::cout << "Recording lowstate to " << opt.output_csv
              << " at " << opt.frequency << " Hz";
    if (opt.duration_s > 0) {
      std::cout << " for " << opt.duration_s << " s";
    } else {
      std::cout << " until Ctrl+C";
    }
    std::cout << "\n";

    while (g_running) {
      const auto now = std::chrono::steady_clock::now();
      const double elapsed = std::chrono::duration<double>(now - start).count();
      if (opt.duration_s > 0 && elapsed >= opt.duration_s) {
        break;
      }

      const auto state = GetFreshState(opt.state_timeout_s);
      WriteRow(out, sample_index, state, elapsed);

      if (sample_index % static_cast<uint64_t>(opt.print_every) == 0) {
        std::cout << "sample=" << sample_index
                  << " elapsed=" << std::fixed << std::setprecision(2) << elapsed
                  << "s mode_machine=" << unsigned(state.mode_machine)
                  << " q15(left_shoulder_pitch)=" << std::setprecision(3) << state.q[15]
                  << " q22(right_shoulder_pitch)=" << state.q[22]
                  << "\n";
      }

      sample_index++;
      next_tick += std::chrono::duration_cast<std::chrono::steady_clock::duration>(period);
      std::this_thread::sleep_until(next_tick);
    }

    out.flush();
    std::cout << "Done. samples=" << sample_index << " output=" << opt.output_csv << "\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "ERROR: " << e.what() << "\n";
    return 1;
  }
}
