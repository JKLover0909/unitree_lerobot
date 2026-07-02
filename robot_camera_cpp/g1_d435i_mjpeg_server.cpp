#include <arpa/inet.h>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iostream>
#include <mutex>
#include <netinet/in.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

#include <librealsense2/rs.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace {

struct Options {
  std::string serial = "243122071229";
  int width = 848;
  int height = 480;
  int fps = 30;
  int port = 8080;
  int jpeg_quality = 80;
  int frame_timeout_ms = 5000;
  int restart_delay_ms = 1000;
  bool enable_depth = false;
};

std::atomic<bool> g_running{true};
std::mutex g_frame_mutex;
std::vector<uchar> g_latest_jpeg;
uint64_t g_frame_count = 0;

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
          << "  --serial SERIAL          RealSense serial, default 243122071229\n"
          << "  --width W                color width, default 848\n"
          << "  --height H               color height, default 480\n"
          << "  --fps FPS                color fps, default 30\n"
          << "  --port PORT              HTTP port, default 8080\n"
          << "  --jpeg-quality Q         1..100, default 80\n"
          << "  --frame-timeout-ms MS    wait_for_frames timeout, default 5000\n"
          << "  --restart-delay-ms MS    delay before restarting camera after timeout, default 1000\n"
          << "  --enable-depth           also enable depth stream for sync/testing\n";
      std::exit(0);
    } else if (arg == "--enable-depth") {
      opt.enable_depth = true;
    } else if (arg == "--serial" || StartsWith(arg, "--serial=")) {
      opt.serial = ValueForArg(i, argc, argv, "--serial");
    } else if (arg == "--width" || StartsWith(arg, "--width=")) {
      opt.width = std::stoi(ValueForArg(i, argc, argv, "--width"));
    } else if (arg == "--height" || StartsWith(arg, "--height=")) {
      opt.height = std::stoi(ValueForArg(i, argc, argv, "--height"));
    } else if (arg == "--fps" || StartsWith(arg, "--fps=")) {
      opt.fps = std::stoi(ValueForArg(i, argc, argv, "--fps"));
    } else if (arg == "--port" || StartsWith(arg, "--port=")) {
      opt.port = std::stoi(ValueForArg(i, argc, argv, "--port"));
    } else if (arg == "--jpeg-quality" || StartsWith(arg, "--jpeg-quality=")) {
      opt.jpeg_quality = std::stoi(ValueForArg(i, argc, argv, "--jpeg-quality"));
    } else if (arg == "--frame-timeout-ms" || StartsWith(arg, "--frame-timeout-ms=")) {
      opt.frame_timeout_ms = std::stoi(ValueForArg(i, argc, argv, "--frame-timeout-ms"));
    } else if (arg == "--restart-delay-ms" || StartsWith(arg, "--restart-delay-ms=")) {
      opt.restart_delay_ms = std::stoi(ValueForArg(i, argc, argv, "--restart-delay-ms"));
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }
  if (opt.width <= 0 || opt.height <= 0 || opt.fps <= 0 || opt.port <= 0) {
    throw std::runtime_error("width/height/fps/port must be positive");
  }
  if (opt.jpeg_quality < 1 || opt.jpeg_quality > 100) {
    throw std::runtime_error("--jpeg-quality must be in range 1..100");
  }
  if (opt.frame_timeout_ms <= 0 || opt.restart_delay_ms < 0) {
    throw std::runtime_error("--frame-timeout-ms must be positive and --restart-delay-ms must be non-negative");
  }
  return opt;
}

void WriteAll(int fd, const void* data, size_t size) {
  const char* ptr = static_cast<const char*>(data);
  while (size > 0) {
    const ssize_t sent = send(fd, ptr, size, MSG_NOSIGNAL);
    if (sent <= 0) {
      throw std::runtime_error("socket send failed");
    }
    ptr += sent;
    size -= static_cast<size_t>(sent);
  }
}

void WriteString(int fd, const std::string& text) {
  WriteAll(fd, text.data(), text.size());
}

std::vector<uchar> GetLatestJpeg() {
  std::lock_guard<std::mutex> lock(g_frame_mutex);
  return g_latest_jpeg;
}

void CaptureThread(const Options opt) {
  const std::vector<int> jpg_params = {
      cv::IMWRITE_JPEG_QUALITY,
      opt.jpeg_quality,
  };

  int restart_count = 0;
  while (g_running) {
    rs2::pipeline pipe;
    rs2::config cfg;
    cfg.enable_device(opt.serial);
    cfg.enable_stream(RS2_STREAM_COLOR, opt.width, opt.height, RS2_FORMAT_BGR8, opt.fps);
    if (opt.enable_depth) {
      cfg.enable_stream(RS2_STREAM_DEPTH, 640, 480, RS2_FORMAT_Z16, opt.fps);
    }

    bool started = false;
    try {
      std::cout << "Starting D435i pipeline: serial=" << opt.serial
                << " color=" << opt.width << "x" << opt.height << "@" << opt.fps
                << " depth=" << (opt.enable_depth ? "on" : "off")
                << " timeout_ms=" << opt.frame_timeout_ms
                << " restart_count=" << restart_count << "\n";
      pipe.start(cfg);
      started = true;
    } catch (const std::exception& e) {
      std::cerr << "Pipeline start error: " << e.what() << "\n";
      if (opt.restart_delay_ms > 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(opt.restart_delay_ms));
      }
      restart_count++;
      continue;
    }

    auto last_print = std::chrono::steady_clock::now();
    uint64_t last_count = g_frame_count;

    while (g_running) {
      rs2::frameset frames;
      try {
        frames = pipe.wait_for_frames(static_cast<unsigned int>(opt.frame_timeout_ms));
      } catch (const std::exception& e) {
        std::cerr << "Capture timeout/error: " << e.what()
                  << ". Restarting D435i pipeline...\n";
        break;
      }

      rs2::video_frame color = frames.get_color_frame();
      if (!color) {
        continue;
      }

      cv::Mat image(cv::Size(opt.width, opt.height), CV_8UC3, const_cast<void*>(color.get_data()), cv::Mat::AUTO_STEP);
      std::vector<uchar> jpeg;
      if (!cv::imencode(".jpg", image, jpeg, jpg_params)) {
        std::cerr << "WARNING: cv::imencode failed\n";
        continue;
      }

      {
        std::lock_guard<std::mutex> lock(g_frame_mutex);
        g_latest_jpeg = std::move(jpeg);
        g_frame_count++;
      }

      const auto now = std::chrono::steady_clock::now();
      const double elapsed = std::chrono::duration<double>(now - last_print).count();
      if (elapsed >= 2.0) {
        uint64_t count = 0;
        {
          std::lock_guard<std::mutex> lock(g_frame_mutex);
          count = g_frame_count;
        }
        std::cout << "capture fps=" << (count - last_count) / elapsed
                  << " frames=" << count << "\n";
        last_count = count;
        last_print = now;
      }
    }

    if (started) {
      try {
        pipe.stop();
      } catch (const std::exception& e) {
        std::cerr << "Pipeline stop warning: " << e.what() << "\n";
      }
      std::cout << "D435i pipeline stopped.\n";
    }

    restart_count++;
    if (g_running && opt.restart_delay_ms > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(opt.restart_delay_ms));
    }
  }
}

std::string ReadHttpRequest(int client_fd) {
  std::string request;
  char buf[1024];
  while (request.find("\r\n\r\n") == std::string::npos && request.size() < 8192) {
    const ssize_t n = recv(client_fd, buf, sizeof(buf), 0);
    if (n <= 0) {
      break;
    }
    request.append(buf, static_cast<size_t>(n));
  }
  return request;
}

void ServeSnapshot(int client_fd) {
  const auto jpeg = GetLatestJpeg();
  if (jpeg.empty()) {
    WriteString(client_fd, "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 17\r\n\r\nNo frame yet.\n");
    return;
  }
  std::ostringstream header;
  header << "HTTP/1.1 200 OK\r\n"
         << "Content-Type: image/jpeg\r\n"
         << "Content-Length: " << jpeg.size() << "\r\n"
         << "Cache-Control: no-cache\r\n\r\n";
  WriteString(client_fd, header.str());
  WriteAll(client_fd, jpeg.data(), jpeg.size());
}

void ServeStream(int client_fd) {
  WriteString(
      client_fd,
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
      "Cache-Control: no-cache\r\n"
      "Pragma: no-cache\r\n\r\n");

  while (g_running) {
    const auto jpeg = GetLatestJpeg();
    if (!jpeg.empty()) {
      std::ostringstream part;
      part << "--frame\r\n"
           << "Content-Type: image/jpeg\r\n"
           << "Content-Length: " << jpeg.size() << "\r\n\r\n";
      WriteString(client_fd, part.str());
      WriteAll(client_fd, jpeg.data(), jpeg.size());
      WriteString(client_fd, "\r\n");
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }
}

void ServeIndex(int client_fd) {
  const std::string body =
      "<html><head><title>G1 D435i</title></head>"
      "<body><h2>G1 D435i MJPEG Stream</h2>"
      "<p><a href=\"/snapshot.jpg\">snapshot.jpg</a></p>"
      "<img src=\"/stream.mjpg\" style=\"max-width:100%;height:auto;\"/>"
      "</body></html>\n";
  std::ostringstream header;
  header << "HTTP/1.1 200 OK\r\n"
         << "Content-Type: text/html\r\n"
         << "Content-Length: " << body.size() << "\r\n\r\n";
  WriteString(client_fd, header.str());
  WriteString(client_fd, body);
}

void ClientThread(int client_fd) {
  try {
    const std::string request = ReadHttpRequest(client_fd);
    if (request.find("GET /snapshot.jpg") != std::string::npos) {
      ServeSnapshot(client_fd);
    } else if (request.find("GET /stream.mjpg") != std::string::npos) {
      ServeStream(client_fd);
    } else {
      ServeIndex(client_fd);
    }
  } catch (const std::exception&) {
    // Client closed the connection.
  }
  close(client_fd);
}

void HttpServerThread(const Options opt) {
  const int server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
    throw std::runtime_error("socket() failed");
  }

  int yes = 1;
  setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(static_cast<uint16_t>(opt.port));

  if (bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
    close(server_fd);
    throw std::runtime_error("bind() failed on port " + std::to_string(opt.port) + ": " + std::strerror(errno));
  }
  if (listen(server_fd, 8) < 0) {
    close(server_fd);
    throw std::runtime_error("listen() failed");
  }

  std::cout << "HTTP server listening on 0.0.0.0:" << opt.port << "\n"
            << "  /             viewer page\n"
            << "  /stream.mjpg  MJPEG stream\n"
            << "  /snapshot.jpg latest JPEG\n";

  while (g_running) {
    sockaddr_in client_addr{};
    socklen_t client_len = sizeof(client_addr);
    const int client_fd = accept(server_fd, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
    if (client_fd < 0) {
      if (g_running) {
        std::cerr << "accept() failed\n";
      }
      continue;
    }
    std::thread(ClientThread, client_fd).detach();
  }

  close(server_fd);
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options opt = ParseArgs(argc, argv);
    std::signal(SIGINT, SignalHandler);
    std::signal(SIGTERM, SignalHandler);

    std::thread capture(CaptureThread, opt);
    std::thread server(HttpServerThread, opt);

    capture.join();
    g_running = false;

    // Poke accept() so the server thread can exit.
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd >= 0) {
      sockaddr_in addr{};
      addr.sin_family = AF_INET;
      addr.sin_addr.s_addr = inet_addr("127.0.0.1");
      addr.sin_port = htons(static_cast<uint16_t>(opt.port));
      connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
      close(fd);
    }
    server.join();
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "ERROR: " << e.what() << "\n";
    return 1;
  }
}
