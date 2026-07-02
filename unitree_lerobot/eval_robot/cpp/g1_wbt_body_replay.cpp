#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <unitree/idl/hg/LowCmd_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/b2/motion_switcher/motion_switcher_client.hpp>
#include <unitree/robot/channel/channel_publisher.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

namespace {

using LowCmd = unitree_hg::msg::dds_::LowCmd_;
using LowState = unitree_hg::msg::dds_::LowState_;

constexpr int kMotorDof = 29;
constexpr int kArmSdkWeightJoint = 29;
constexpr const char* kLowCmdTopic = "rt/lowcmd";
constexpr const char* kArmSdkTopic = "rt/arm_sdk";
constexpr const char* kLowStateTopic = "rt/lowstate";
constexpr const char* kControlConfirmation = "SEND_FULL_BODY_G1_WBT";

const std::array<std::string, kMotorDof> kJointNames = {
    "left_hip_pitch",      "left_hip_roll",       "left_hip_yaw",
    "left_knee",           "left_ankle_pitch",    "left_ankle_roll",
    "right_hip_pitch",     "right_hip_roll",      "right_hip_yaw",
    "right_knee",          "right_ankle_pitch",   "right_ankle_roll",
    "waist_yaw",           "waist_roll",          "waist_pitch",
    "left_shoulder_pitch", "left_shoulder_roll",  "left_shoulder_yaw",
    "left_elbow",          "left_wrist_roll",     "left_wrist_pitch",
    "left_wrist_yaw",      "right_shoulder_pitch","right_shoulder_roll",
    "right_shoulder_yaw",  "right_elbow",         "right_wrist_roll",
    "right_wrist_pitch",   "right_wrist_yaw",
};

const std::array<float, kMotorDof> kBaseKp = {
    60, 60, 60, 100, 40, 40, 60, 60, 60, 100, 40, 40, 60, 40, 40,
    40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40,
};

const std::array<float, kMotorDof> kBaseKd = {
    1, 1, 1, 2, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
};

const std::vector<std::pair<std::string, std::pair<int, int>>> kInitGroups = {
    {"left_leg", {0, 6}},
    {"right_leg", {6, 12}},
    {"waist", {12, 15}},
    {"left_arm", {15, 22}},
    {"right_arm", {22, 29}},
};

struct Options {
  std::string input_csv;
  std::string network_interface;
  std::string log_csv;
  double frequency = 30.0;
  int max_steps = -1;
  int print_every = 50;
  bool send_actions = false;
  std::string control_confirmation;
  bool release_motion_mode = false;
  bool arm_sdk = false;
  bool initialize_from_first_row = false;
  bool init_only = false;
  bool init_sequential = false;
  std::string init_joints_raw;
  double init_group_pause_s = 1.0;
  double initialization_speed_rad_s = 0.10;
  double initialization_timeout_s = 180.0;
  double initialization_max_error_rad = 0.10;
  double max_body_delta_rad = 0.015;
  double low_body_kp_scale = 0.35;
  double arm_kp_scale = 1.0;
  double state_timeout_s = 5.0;
};

struct CsvRow {
  int episode = 0;
  int action_step = 0;
  int dataset_index = 0;
  int frame_index = 0;
  std::array<float, kMotorDof> q{};
};

struct RobotState {
  std::array<float, kMotorDof> q{};
  std::array<float, kMotorDof> dq{};
  uint8_t mode_machine = 0;
  std::chrono::steady_clock::time_point timestamp;
};

uint32_t Crc32Core(uint32_t* ptr, uint32_t len) {
  uint32_t xbit = 0;
  uint32_t data = 0;
  uint32_t crc32 = 0xFFFFFFFF;
  constexpr uint32_t kPolynomial = 0x04c11db7;
  for (uint32_t i = 0; i < len; i++) {
    xbit = 1 << 31;
    data = ptr[i];
    for (uint32_t bits = 0; bits < 32; bits++) {
      if (crc32 & 0x80000000) {
        crc32 <<= 1;
        crc32 ^= kPolynomial;
      } else {
        crc32 <<= 1;
      }
      if (data & xbit) {
        crc32 ^= kPolynomial;
      }
      xbit >>= 1;
    }
  }
  return crc32;
}

void PrintUsage(const char* argv0) {
  std::cout
      << "Usage:\n"
      << "  " << argv0 << " --input-csv actions.csv [options]\n\n"
      << "Options:\n"
      << "  --network-interface IFACE\n"
      << "  --frequency HZ                         default 30\n"
      << "  --max-steps N                          limit replay rows\n"
      << "  --print-every N                        default 50\n"
      << "  --log-csv PATH                         write replay log\n"
      << "  --initialize-from-first-row            move to first CSV pose before replay\n"
      << "  --init-only                            exit after initialization, before replay prompt\n"
      << "  --initialization-speed-rad-s V         default 0.10\n"
      << "  --initialization-timeout-s V           default 180\n"
      << "  --initialization-max-error-rad V       default 0.10\n"
      << "  --init-sequential                      init left leg, right leg, waist, left arm, right arm\n"
      << "  --init-group-pause-s V                 default 1\n"
      << "  --init-joints 4,5,10,11                init only selected joints\n"
      << "  --max-body-delta-rad V                 default 0.015\n"
      << "  --low-body-kp-scale V                  default 0.35 for joints 0:15\n"
      << "  --arm-kp-scale V                       default 1.0 for joints 15:29\n"
      << "  --arm-sdk                              publish to rt/arm_sdk; only valid for waist/arms 12..28\n"
      << "  --release-motion-mode                  call MotionSwitcher.ReleaseMode first\n"
      << "  --send-actions                         actually publish the selected command topic\n"
      << "  --control-confirmation " << kControlConfirmation << "\n";
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

std::vector<int> ParseInitJoints(const std::string& raw);

Options ParseArgs(int argc, char** argv) {
  Options opt;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--help" || arg == "-h") {
      PrintUsage(argv[0]);
      std::exit(0);
    } else if (arg == "--send-actions") {
      opt.send_actions = true;
    } else if (arg == "--release-motion-mode") {
      opt.release_motion_mode = true;
    } else if (arg == "--arm-sdk") {
      opt.arm_sdk = true;
    } else if (arg == "--initialize-from-first-row") {
      opt.initialize_from_first_row = true;
    } else if (arg == "--init-only") {
      opt.init_only = true;
    } else if (arg == "--init-sequential") {
      opt.init_sequential = true;
    } else if (arg == "--input-csv" || StartsWith(arg, "--input-csv=")) {
      opt.input_csv = ValueForArg(i, argc, argv, "--input-csv");
    } else if (arg == "--network-interface" || StartsWith(arg, "--network-interface=")) {
      opt.network_interface = ValueForArg(i, argc, argv, "--network-interface");
    } else if (arg == "--log-csv" || StartsWith(arg, "--log-csv=")) {
      opt.log_csv = ValueForArg(i, argc, argv, "--log-csv");
    } else if (arg == "--frequency" || StartsWith(arg, "--frequency=")) {
      opt.frequency = std::stod(ValueForArg(i, argc, argv, "--frequency"));
    } else if (arg == "--max-steps" || StartsWith(arg, "--max-steps=")) {
      opt.max_steps = std::stoi(ValueForArg(i, argc, argv, "--max-steps"));
    } else if (arg == "--print-every" || StartsWith(arg, "--print-every=")) {
      opt.print_every = std::stoi(ValueForArg(i, argc, argv, "--print-every"));
    } else if (arg == "--control-confirmation" || StartsWith(arg, "--control-confirmation=")) {
      opt.control_confirmation = ValueForArg(i, argc, argv, "--control-confirmation");
    } else if (arg == "--init-joints" || StartsWith(arg, "--init-joints=")) {
      opt.init_joints_raw = ValueForArg(i, argc, argv, "--init-joints");
    } else if (arg == "--init-group-pause-s" || StartsWith(arg, "--init-group-pause-s=")) {
      opt.init_group_pause_s = std::stod(ValueForArg(i, argc, argv, "--init-group-pause-s"));
    } else if (arg == "--initialization-speed-rad-s" || StartsWith(arg, "--initialization-speed-rad-s=")) {
      opt.initialization_speed_rad_s = std::stod(ValueForArg(i, argc, argv, "--initialization-speed-rad-s"));
    } else if (arg == "--initialization-timeout-s" || StartsWith(arg, "--initialization-timeout-s=")) {
      opt.initialization_timeout_s = std::stod(ValueForArg(i, argc, argv, "--initialization-timeout-s"));
    } else if (arg == "--initialization-max-error-rad" || StartsWith(arg, "--initialization-max-error-rad=")) {
      opt.initialization_max_error_rad = std::stod(ValueForArg(i, argc, argv, "--initialization-max-error-rad"));
    } else if (arg == "--max-body-delta-rad" || StartsWith(arg, "--max-body-delta-rad=")) {
      opt.max_body_delta_rad = std::stod(ValueForArg(i, argc, argv, "--max-body-delta-rad"));
    } else if (arg == "--low-body-kp-scale" || StartsWith(arg, "--low-body-kp-scale=")) {
      opt.low_body_kp_scale = std::stod(ValueForArg(i, argc, argv, "--low-body-kp-scale"));
    } else if (arg == "--arm-kp-scale" || StartsWith(arg, "--arm-kp-scale=")) {
      opt.arm_kp_scale = std::stod(ValueForArg(i, argc, argv, "--arm-kp-scale"));
    } else if (arg == "--state-timeout-s" || StartsWith(arg, "--state-timeout-s=")) {
      opt.state_timeout_s = std::stod(ValueForArg(i, argc, argv, "--state-timeout-s"));
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }

  if (opt.input_csv.empty()) {
    throw std::runtime_error("--input-csv is required");
  }
  if (opt.frequency <= 0) {
    throw std::runtime_error("--frequency must be positive");
  }
  if (opt.max_steps == 0) {
    throw std::runtime_error("--max-steps must be positive when provided");
  }
  if (opt.print_every <= 0) {
    throw std::runtime_error("--print-every must be positive");
  }
  if (opt.initialization_speed_rad_s <= 0 || opt.initialization_timeout_s <= 0 ||
      opt.initialization_max_error_rad <= 0 || opt.max_body_delta_rad <= 0) {
    throw std::runtime_error("Initialization and delta parameters must be positive");
  }
  if (opt.init_sequential && !opt.init_joints_raw.empty()) {
    throw std::runtime_error("--init-joints and --init-sequential cannot be used together");
  }
  if (opt.send_actions && opt.control_confirmation != kControlConfirmation) {
    throw std::runtime_error(std::string("Real robot control requires --control-confirmation=") + kControlConfirmation);
  }
  if (opt.init_only && !opt.initialize_from_first_row) {
    throw std::runtime_error("--init-only requires --initialize-from-first-row");
  }
  if (opt.arm_sdk) {
    if (!opt.initialize_from_first_row || !opt.init_only || opt.init_joints_raw.empty()) {
      throw std::runtime_error("--arm-sdk currently requires --initialize-from-first-row --init-only --init-joints=12..28");
    }
    const auto joints = ParseInitJoints(opt.init_joints_raw);
    for (const int joint : joints) {
      if (joint < 12 || joint >= kMotorDof) {
        throw std::runtime_error("--arm-sdk can only command waist/arm joints 12..28, got " + std::to_string(joint));
      }
    }
  }
  return opt;
}

std::vector<std::string> SplitCsvLine(const std::string& line) {
  std::vector<std::string> cells;
  std::stringstream ss(line);
  std::string cell;
  while (std::getline(ss, cell, ',')) {
    cells.push_back(cell);
  }
  if (!line.empty() && line.back() == ',') {
    cells.emplace_back();
  }
  return cells;
}

int ColumnIndex(const std::map<std::string, int>& columns, const std::string& name) {
  const auto it = columns.find(name);
  if (it == columns.end()) {
    throw std::runtime_error("CSV is missing required column: " + name);
  }
  return it->second;
}

std::vector<CsvRow> LoadCsv(const std::string& path, int max_steps) {
  std::ifstream f(path);
  if (!f) {
    throw std::runtime_error("Could not open CSV: " + path);
  }
  std::string header_line;
  if (!std::getline(f, header_line)) {
    throw std::runtime_error("CSV is empty: " + path);
  }
  const auto header = SplitCsvLine(header_line);
  std::map<std::string, int> columns;
  for (int i = 0; i < static_cast<int>(header.size()); ++i) {
    columns[header[i]] = i;
  }
  std::array<int, kMotorDof> q_cols{};
  for (int i = 0; i < kMotorDof; ++i) {
    q_cols[i] = ColumnIndex(columns, "q" + std::to_string(i));
  }
  const int ep_col = ColumnIndex(columns, "episode");
  const int action_col = ColumnIndex(columns, "action_step");
  const int dataset_col = ColumnIndex(columns, "dataset_index");
  const int frame_col = ColumnIndex(columns, "frame_index");

  std::vector<CsvRow> rows;
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) {
      continue;
    }
    const auto cells = SplitCsvLine(line);
    if (cells.size() < header.size()) {
      throw std::runtime_error("Malformed CSV row with too few columns: " + line);
    }
    CsvRow row;
    row.episode = std::stoi(cells[ep_col]);
    row.action_step = std::stoi(cells[action_col]);
    row.dataset_index = std::stoi(cells[dataset_col]);
    row.frame_index = std::stoi(cells[frame_col]);
    for (int i = 0; i < kMotorDof; ++i) {
      row.q[i] = std::stof(cells[q_cols[i]]);
    }
    rows.push_back(row);
    if (max_steps > 0 && static_cast<int>(rows.size()) >= max_steps) {
      break;
    }
  }
  if (rows.empty()) {
    throw std::runtime_error("CSV contains no replay rows: " + path);
  }
  return rows;
}

std::vector<int> ParseInitJoints(const std::string& raw) {
  std::vector<int> result;
  if (raw.empty()) {
    return result;
  }
  std::stringstream ss(raw);
  std::string token;
  while (std::getline(ss, token, ',')) {
    if (token.empty()) {
      continue;
    }
    const int idx = std::stoi(token);
    if (idx < 0 || idx >= kMotorDof) {
      throw std::runtime_error("--init-joints contains out-of-range index: " + std::to_string(idx));
    }
    result.push_back(idx);
  }
  std::sort(result.begin(), result.end());
  result.erase(std::unique(result.begin(), result.end()), result.end());
  return result;
}

std::array<float, kMotorDof> ClipStep(
    const std::array<float, kMotorDof>& target,
    const std::array<float, kMotorDof>& current,
    double max_delta) {
  std::array<float, kMotorDof> result{};
  for (int i = 0; i < kMotorDof; ++i) {
    const float delta = target[i] - current[i];
    result[i] = current[i] + std::clamp(delta, static_cast<float>(-max_delta), static_cast<float>(max_delta));
  }
  return result;
}

double MaxAbsError(
    const std::array<float, kMotorDof>& target,
    const std::array<float, kMotorDof>& current,
    const std::vector<int>* active_joints = nullptr) {
  double err = 0.0;
  if (active_joints != nullptr) {
    for (const int i : *active_joints) {
      err = std::max(err, std::abs(static_cast<double>(target[i] - current[i])));
    }
    return err;
  }
  for (int i = 0; i < kMotorDof; ++i) {
    err = std::max(err, std::abs(static_cast<double>(target[i] - current[i])));
  }
  return err;
}

double Norm(const std::array<float, kMotorDof>& values) {
  double sum = 0.0;
  for (const float v : values) {
    sum += static_cast<double>(v) * static_cast<double>(v);
  }
  return std::sqrt(sum);
}

class G1LowCmdController {
 public:
  explicit G1LowCmdController(const Options& opt) : arm_sdk_(opt.arm_sdk) {
    if (opt.network_interface.empty()) {
      unitree::robot::ChannelFactory::Instance()->Init(0);
    } else {
      unitree::robot::ChannelFactory::Instance()->Init(0, opt.network_interface);
    }

    InspectOrReleaseMotionMode(opt.release_motion_mode);

    const std::string command_topic = arm_sdk_ ? kArmSdkTopic : kLowCmdTopic;
    std::cout << "Command topic: " << command_topic;
    if (arm_sdk_) {
      std::cout << " (arm SDK weight joint " << kArmSdkWeightJoint << " = 1.0)";
    }
    std::cout << "\n";
    publisher_.reset(new unitree::robot::ChannelPublisher<LowCmd>(command_topic));
    publisher_->InitChannel();

    subscriber_.reset(new unitree::robot::ChannelSubscriber<LowState>(kLowStateTopic));
    subscriber_->InitChannel(
        std::bind(&G1LowCmdController::LowStateHandler, this, std::placeholders::_1), 10);

    const RobotState first = WaitState(opt.state_timeout_s);
    mode_machine_ = first.mode_machine;
    InitializeCommandTemplate(first, opt);
    std::cout << "Connected to rt/lowstate: mode_machine=" << unsigned(mode_machine_) << "\n";
  }

  RobotState WaitState(double timeout_s) const {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(timeout_s);
    while (std::chrono::steady_clock::now() < deadline) {
      const auto maybe_state = GetState(timeout_s);
      if (maybe_state.has_value()) {
        return maybe_state.value();
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    throw std::runtime_error("No fresh rt/lowstate received within timeout");
  }

  std::array<float, kMotorDof> CurrentQ(double timeout_s) const {
    return WaitState(timeout_s).q;
  }

  void PublishBody(
      const std::array<float, kMotorDof>& q_target,
      double low_body_kp_scale,
      double arm_kp_scale,
      const std::vector<int>* active_joints = nullptr) {
    LowCmd cmd = command_template_;
    cmd.mode_pr() = 0;
    cmd.mode_machine() = mode_machine_;
    if (arm_sdk_) {
      cmd.motor_cmd().at(kArmSdkWeightJoint).q() = 1.0F;
    }

    for (int i = 0; i < kMotorDof; ++i) {
      bool active = true;
      if (active_joints != nullptr) {
        active = std::binary_search(active_joints->begin(), active_joints->end(), i);
      }
      cmd.motor_cmd().at(i).mode() = 1;
      cmd.motor_cmd().at(i).tau() = 0.0F;
      cmd.motor_cmd().at(i).dq() = 0.0F;
      if (!active) {
        if (arm_sdk_) {
          // Match the existing Python G1_29_ArmController: keep non-commanded
          // joints locked at the command template instead of disabling them.
          continue;
        } else {
          cmd.motor_cmd().at(i).kp() = 0.0F;
          cmd.motor_cmd().at(i).kd() = 0.5F;
        }
      } else {
        cmd.motor_cmd().at(i).q() = q_target[i];
        const double scale = (i < 15) ? low_body_kp_scale : arm_kp_scale;
        cmd.motor_cmd().at(i).kp() = static_cast<float>(kBaseKp[i] * scale);
        cmd.motor_cmd().at(i).kd() = kBaseKd[i];
      }
    }

    cmd.crc() = Crc32Core(reinterpret_cast<uint32_t*>(&cmd), (sizeof(cmd) >> 2) - 1);
    publisher_->Write(cmd);
  }

 private:
  void InitializeCommandTemplate(const RobotState& state, const Options& opt) {
    command_template_.mode_pr() = 0;
    command_template_.mode_machine() = state.mode_machine;
    if (arm_sdk_) {
      command_template_.motor_cmd().at(kArmSdkWeightJoint).q() = 1.0F;
    }
    for (int i = 0; i < kMotorDof; ++i) {
      command_template_.motor_cmd().at(i).mode() = 1;
      command_template_.motor_cmd().at(i).tau() = 0.0F;
      command_template_.motor_cmd().at(i).q() = state.q[i];
      command_template_.motor_cmd().at(i).dq() = 0.0F;
      const double scale = (i < 15) ? opt.low_body_kp_scale : opt.arm_kp_scale;
      command_template_.motor_cmd().at(i).kp() = static_cast<float>(kBaseKp[i] * scale);
      command_template_.motor_cmd().at(i).kd() = kBaseKd[i];
    }
  }

  void LowStateHandler(const void* message) {
    const LowState low_state = *(const LowState*)message;
    if (low_state.crc() !=
        Crc32Core((uint32_t*)&low_state, (sizeof(LowState) >> 2) - 1)) {
      std::cout << "WARNING: rt/lowstate CRC error\n";
      return;
    }
    RobotState state;
    for (int i = 0; i < kMotorDof; ++i) {
      state.q[i] = low_state.motor_state().at(i).q();
      state.dq[i] = low_state.motor_state().at(i).dq();
    }
    state.mode_machine = low_state.mode_machine();
    state.timestamp = std::chrono::steady_clock::now();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      state_ = state;
    }
  }

  std::optional<RobotState> GetState(double max_age_s) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!state_.has_value()) {
      return std::nullopt;
    }
    const auto age = std::chrono::duration<double>(std::chrono::steady_clock::now() - state_->timestamp).count();
    if (age > max_age_s) {
      return std::nullopt;
    }
    return state_;
  }

  void InspectOrReleaseMotionMode(bool release) {
    auto msc = std::make_shared<unitree::robot::b2::MotionSwitcherClient>();
    msc->SetTimeout(5.0F);
    msc->Init();
    std::string form;
    std::string name;
    int32_t ret = msc->CheckMode(form, name);
    std::cout << "G1 MotionSwitcher: ret=" << ret << " form=" << form << " name=" << name << "\n";
    if (!release) {
      return;
    }
    int attempts = 0;
    while (!name.empty() && attempts < 3) {
      std::cout << "Releasing active motion mode before low-level control...\n";
      const int32_t release_ret = msc->ReleaseMode();
      std::cout << "ReleaseMode ret=" << release_ret << "\n";
      std::this_thread::sleep_for(std::chrono::seconds(5));
      form.clear();
      name.clear();
      ret = msc->CheckMode(form, name);
      std::cout << "G1 MotionSwitcher after release: ret=" << ret << " form=" << form << " name=" << name << "\n";
      attempts += 1;
    }
  }

  uint8_t mode_machine_ = 0;
  bool arm_sdk_ = false;
  LowCmd command_template_;
  std::shared_ptr<unitree::robot::ChannelPublisher<LowCmd>> publisher_;
  std::shared_ptr<unitree::robot::ChannelSubscriber<LowState>> subscriber_;
  mutable std::mutex mutex_;
  std::optional<RobotState> state_;
};

void InitializeFullBody(G1LowCmdController& io, const std::array<float, kMotorDof>& target, const Options& opt) {
  std::cout << "Initializing full body to first CSV joint pose...\n";
  const double max_step = opt.initialization_speed_rad_s / opt.frequency;
  const auto start = std::chrono::steady_clock::now();
  auto last_print = start - std::chrono::seconds(10);
  while (true) {
    const auto current = io.CurrentQ(opt.state_timeout_s);
    const double error = MaxAbsError(target, current);
    if (error <= opt.initialization_max_error_rad) {
      std::cout << "Initial body pose reached: max_error=" << std::fixed << std::setprecision(3) << error << " rad\n";
      return;
    }
    const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    if (elapsed > opt.initialization_timeout_s) {
      throw std::runtime_error("Timed out initializing body pose: max_error=" + std::to_string(error));
    }
    const auto command = ClipStep(target, current, max_step);
    io.PublishBody(command, opt.low_body_kp_scale, opt.arm_kp_scale);
    const auto now = std::chrono::steady_clock::now();
    if (std::chrono::duration<double>(now - last_print).count() >= 1.0) {
      std::cout << "Initializing body: elapsed=" << std::fixed << std::setprecision(1) << elapsed
                << "s max_error=" << std::setprecision(3) << error << " rad\n";
      last_print = now;
    }
    std::this_thread::sleep_for(std::chrono::duration<double>(1.0 / opt.frequency));
  }
}

void InitializeSelectedJoints(
    G1LowCmdController& io,
    const std::array<float, kMotorDof>& target,
    const Options& opt,
    const std::vector<int>& joints) {
  std::cout << "Initializing selected joints:";
  for (const int i : joints) {
    std::cout << " " << i << "(" << kJointNames[i] << ")";
  }
  std::cout << "\n";

  const double max_step = opt.initialization_speed_rad_s / opt.frequency;
  const auto initial = io.CurrentQ(opt.state_timeout_s);
  const auto start = std::chrono::steady_clock::now();
  auto last_print = start - std::chrono::seconds(10);
  while (true) {
    const auto current = io.CurrentQ(opt.state_timeout_s);
    auto command = current;
    for (const int i : joints) {
      const float delta = target[i] - current[i];
      command[i] = current[i] + std::clamp(delta, static_cast<float>(-max_step), static_cast<float>(max_step));
    }
    io.PublishBody(command, opt.low_body_kp_scale, opt.arm_kp_scale, &joints);
    const double error = MaxAbsError(target, current, &joints);
    const double moved = MaxAbsError(current, initial, &joints);
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration<double>(now - start).count();
    if (error <= opt.initialization_max_error_rad) {
      std::cout << "Selected joints reached target: max_error=" << std::fixed << std::setprecision(3) << error << " rad\n";
      return;
    }
    if (elapsed > opt.initialization_timeout_s) {
      throw std::runtime_error("Timed out initializing selected joints: max_error=" + std::to_string(error));
    }
    if (std::chrono::duration<double>(now - last_print).count() >= 1.0) {
      std::cout << "  elapsed=" << std::fixed << std::setprecision(1) << elapsed
                << "s max_error=" << std::setprecision(3) << error
                << " rad moved=" << moved << " rad\n";
      if (!joints.empty()) {
        const int i = joints.front();
        std::cout << "    sample " << i << "(" << kJointNames[i] << ")"
                  << " current=" << current[i]
                  << " target=" << target[i]
                  << " command=" << command[i] << "\n";
      }
      last_print = now;
      if (elapsed >= 3.0 && moved < 0.005) {
        throw std::runtime_error(
            "Commands are being published but no selected-joint motion was detected. "
            "For --arm-sdk, confirm the G1 is in Regular motion-control mode (R1+X), not Debug/development mode (L2+R2). "
            "For rt/lowcmd, the active motion mode may be overriding low-level commands.");
      }
    }
    std::this_thread::sleep_for(std::chrono::duration<double>(1.0 / opt.frequency));
  }
}

void InitializeSequential(G1LowCmdController& io, const std::array<float, kMotorDof>& target, const Options& opt) {
  std::cout << "Sequential init: 5 groups, speed=" << opt.initialization_speed_rad_s
            << " rad/s, pause=" << opt.init_group_pause_s << "s\n";
  for (size_t group_idx = 0; group_idx < kInitGroups.size(); ++group_idx) {
    const auto& group = kInitGroups[group_idx];
    std::vector<int> active;
    for (int i = group.second.first; i < group.second.second; ++i) {
      active.push_back(i);
    }
    std::cout << "\n[" << (group_idx + 1) << "/5] Initializing " << group.first
              << " joints " << group.second.first << ":" << group.second.second << "\n";
    InitializeSelectedJoints(io, target, opt, active);
    if (group_idx + 1 < kInitGroups.size() && opt.init_group_pause_s > 0) {
      std::cout << "Pausing " << opt.init_group_pause_s << "s before next group...\n";
      std::this_thread::sleep_for(std::chrono::duration<double>(opt.init_group_pause_s));
    }
  }
  std::cout << "Sequential init complete.\n";
}

void WriteLogHeader(std::ofstream& f) {
  f << "action_step,episode,dataset_index,frame_index,dry_run,max_body_delta,body_target_norm,body_command_norm\n";
}

void ReplayRows(const std::vector<CsvRow>& rows, const Options& opt, G1LowCmdController* io) {
  std::ofstream log;
  if (!opt.log_csv.empty()) {
    log.open(opt.log_csv);
    if (!log) {
      throw std::runtime_error("Could not open log CSV: " + opt.log_csv);
    }
    WriteLogHeader(log);
  }

  std::array<float, kMotorDof> body_last{};
  if (io != nullptr) {
    if (opt.initialize_from_first_row) {
      const auto joints = ParseInitJoints(opt.init_joints_raw);
      if (opt.init_sequential) {
        InitializeSequential(*io, rows.front().q, opt);
      } else if (!joints.empty()) {
        InitializeSelectedJoints(*io, rows.front().q, opt, joints);
      } else {
        InitializeFullBody(*io, rows.front().q, opt);
      }
    }
    if (opt.init_only) {
      std::cout << "Init-only requested; exiting before replay.\n";
      return;
    }
    std::cout << "Initial pose stage done. Enter 's' to start C++ full-body replay, anything else to stop: ";
    std::string input;
    std::getline(std::cin, input);
    if (input != "s" && input != "S") {
      std::cout << "Stopped before replay.\n";
      return;
    }
    body_last = io->CurrentQ(opt.state_timeout_s);
  }

  std::cout << "Starting C++ full-body CSV playback: rows=" << rows.size()
            << " dry_run=" << (io == nullptr ? "true" : "false") << "\n";
  for (size_t step = 0; step < rows.size(); ++step) {
    const auto loop_start = std::chrono::steady_clock::now();
    const auto& row = rows[step];
    std::array<float, kMotorDof> command = row.q;
    double max_delta = 0.0;
    if (io != nullptr) {
      command = ClipStep(row.q, body_last, opt.max_body_delta_rad);
      max_delta = MaxAbsError(command, body_last);
      io->PublishBody(command, opt.low_body_kp_scale, opt.arm_kp_scale);
      body_last = command;
    }

    if (log) {
      log << (step + 1) << "," << row.episode << "," << row.dataset_index << "," << row.frame_index << ","
          << (io == nullptr ? "true" : "false") << "," << max_delta << "," << Norm(row.q) << "," << Norm(command) << "\n";
    }
    if (((step + 1) % static_cast<size_t>(opt.print_every) == 0) || step + 1 == rows.size()) {
      std::cout << "action_step=" << (step + 1) << "/" << rows.size()
                << " episode=" << row.episode
                << " dataset_index=" << row.dataset_index
                << " max_delta=" << std::fixed << std::setprecision(4) << max_delta
                << " dry_run=" << (io == nullptr ? "true" : "false") << "\n";
    }
    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - loop_start).count();
    const double sleep_s = std::max(0.0, (1.0 / opt.frequency) - elapsed);
    std::this_thread::sleep_for(std::chrono::duration<double>(sleep_s));
  }
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options opt = ParseArgs(argc, argv);
    const auto rows = LoadCsv(opt.input_csv, opt.max_steps);
    std::cout << "Loaded CSV: " << opt.input_csv << " rows=" << rows.size()
              << " first_episode=" << rows.front().episode
              << " first_dataset_index=" << rows.front().dataset_index << "\n";

    if (!opt.send_actions) {
      ReplayRows(rows, opt, nullptr);
      return 0;
    }

    G1LowCmdController io(opt);
    ReplayRows(rows, opt, &io);
    return 0;
  } catch (const std::exception& exc) {
    std::cerr << "ERROR: " << exc.what() << "\n";
    return 1;
  }
}
