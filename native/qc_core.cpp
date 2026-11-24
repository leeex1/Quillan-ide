// quillancode native core: fast filesystem + search hot paths.
// Build: clang++ -O3 -std=c++17 -o qc_core.exe qc_core.cpp
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static bool excluded(const std::string &name) {
    return name == ".git" || name == "node_modules" || name == "__pycache__" ||
           name == ".venv" || name == "venv";
}

static bool wildcard_match(const std::string &text, const std::string &pattern) {
    size_t t = 0, p = 0, star = std::string::npos, mark = 0;
    while (t < text.size()) {
        if (p < pattern.size() && (pattern[p] == '?' || pattern[p] == text[t])) {
            ++p; ++t;
        } else if (p < pattern.size() && pattern[p] == '*') {
            star = p++; mark = t;
        } else if (star != std::string::npos) {
            p = star + 1; t = ++mark;
        } else {
            return false;
        }
    }
    while (p < pattern.size() && pattern[p] == '*') ++p;
    return p == pattern.size();
}

static std::string rel_path(const fs::path &root, const fs::path &path) {
    std::error_code ec;
    fs::path rel = fs::relative(path, root, ec);
    if (ec) return path.string();
    return rel.generic_string();
}

static bool confined(const fs::path &root, const fs::path &candidate, fs::path &out) {
    std::error_code ec;
    fs::path base = fs::weakly_canonical(root, ec);
    fs::path p = candidate.is_absolute() ? candidate : (base / candidate);
    fs::path resolved = fs::weakly_canonical(p, ec);
    if (ec) return false;
    auto a = base.string(), b = resolved.string();
    if (b.rfind(a, 0) != 0) return false;
    if (b.size() > a.size() && b[a.size()] != '/' && b[a.size()] != '\\') return false;
    out = resolved;
    return true;
}

static std::vector<fs::path> files(const fs::path &root) {
    std::vector<fs::path> out;
    std::error_code ec;
    for (fs::recursive_directory_iterator it(root, ec), end; it != end; it.increment(ec)) {
        if (ec) break;
        if (it->is_directory(ec) && excluded(it->path().filename().string())) {
            it.disable_recursion_pending();
            continue;
        }
        if (it->is_regular_file(ec)) out.push_back(it->path());
    }
    return out;
}

static std::string read_file(const fs::path &p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) return "";
    return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

static std::string stdin_all() {
    std::ostringstream ss;
    ss << std::cin.rdbuf();
    return ss.str();
}

static int cmd_glob(const fs::path &root, const std::string &pattern, size_t limit) {
    size_t count = 0;
    for (const auto &p : files(root)) {
        std::string rel = rel_path(root, p);
        if (wildcard_match(rel, pattern) || wildcard_match(p.filename().string(), pattern)) {
            std::cout << rel << "\n";
            if (++count >= limit) break;
        }
    }
    return 0;
}

static int cmd_grep(const fs::path &root, const std::string &pattern,
                    const std::string &filter, size_t limit) {
    std::regex re;
    try { re = std::regex(pattern); }
    catch (const std::regex_error &e) { std::cerr << "invalid regex: " << e.what() << "\n"; return 2; }
    size_t count = 0;
    for (const auto &p : files(root)) {
        if (filter != "*" && !wildcard_match(p.filename().string(), filter)) continue;
        std::string content = read_file(p);
        if (content.find('\0') != std::string::npos) continue;
        std::string rel = rel_path(root, p);
        size_t line_no = 0, start = 0;
        while (start <= content.size()) {
            size_t end = content.find('\n', start);
            std::string line = content.substr(start, end == std::string::npos ? std::string::npos : end - start);
            if (!line.empty() && line.back() == '\r') line.pop_back();
            ++line_no;
            if (std::regex_search(line, re)) {
                std::cout << rel << ":" << line_no << ": " << line << "\n";
                if (++count >= limit) return 0;
            }
            if (end == std::string::npos) break;
            start = end + 1;
        }
    }
    return 0;
}

static int cmd_read(const fs::path &root, const std::string &target, size_t offset, size_t limit) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cerr << "path escapes workspace\n"; return 3; }
    std::ifstream in(resolved, std::ios::binary);
    if (!in) { std::cerr << "not a file\n"; return 2; }
    std::string line;
    size_t n = 0;
    while (std::getline(in, line) && n < offset + limit) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (n >= offset) std::cout << (n + 1) << " | " << line << "\n";
        ++n;
    }
    return 0;
}

static int cmd_write(const fs::path &root, const std::string &target) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cerr << "path escapes workspace\n"; return 3; }
    std::error_code ec;
    fs::create_directories(resolved.parent_path(), ec);
    if (ec) { std::cerr << "mkdir failed\n"; return 2; }
    std::string data = stdin_all();
    std::ofstream out(resolved, std::ios::binary | std::ios::trunc);
    out.write(data.data(), static_cast<std::streamsize>(data.size()));
    if (!out) { std::cerr << "write failed\n"; return 2; }
    std::cout << "wrote " << data.size() << " bytes\n";
    return 0;
}

static int cmd_edit(const fs::path &root, const std::string &target,
                    const std::string &old, const std::string &replacement, bool all) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cerr << "path escapes workspace\n"; return 3; }
    std::string text = read_file(resolved);
    size_t count = 0, pos = 0;
    while ((pos = text.find(old, pos)) != std::string::npos) {
        ++count;
        if (!all) break;
        pos += old.size();
    }
    if (!count) { std::cerr << "old text not found\n"; return 2; }
    if (count > 1 && !all) { std::cerr << "ambiguous match\n"; return 2; }
    if (all) {
        std::string out;
        pos = 0;
        while ((pos = text.find(old, pos)) != std::string::npos) {
            out += text.substr(0, pos) + replacement;
            pos += old.size();
        }
        out += text.substr(pos);
        text = out;
    } else {
        pos = text.find(old);
        text.replace(pos, old.size(), replacement);
    }
    std::ofstream out(resolved, std::ios::binary | std::ios::trunc);
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
    std::cout << "replaced " << (all ? count : 1) << " occurrence(s)\n";
    return 0;
}

static int cmd_list(const fs::path &root, const std::string &target) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cerr << "path escapes workspace\n"; return 3; }
    std::error_code ec;
    if (!fs::is_directory(resolved, ec)) { std::cerr << "not a directory\n"; return 2; }
    std::vector<std::pair<std::string, bool>> entries;
    for (fs::directory_iterator it(resolved, ec), end; it != end; it.increment(ec)) {
        entries.push_back({it->path().filename().string(), it->is_directory(ec)});
    }
    std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b) {
        if (a.second != b.second) return b.second;
        return a.first < b.first;
    });
    for (const auto &e : entries) std::cout << (e.second ? "d  " : "f  ") << e.first << "\n";
    return 0;
}

static uint64_t fnv1a(const std::string &s) {
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char c : s) { h ^= c; h *= 1099511628211ULL; }
    return h;
}

static int cmd_hash(const fs::path &root, const std::string &target) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cerr << "path escapes workspace\n"; return 3; }
    char buf[65536];
    uint64_t h = 1469598103934665603ULL;
    std::ifstream in(resolved, std::ios::binary);
    while (in) {
        in.read(buf, sizeof(buf));
        std::streamsize n = in.gcount();
        for (std::streamsize i = 0; i < n; ++i) {
            h ^= static_cast<unsigned char>(buf[i]);
            h *= 1099511628211ULL;
        }
    }
    std::cout << std::hex << h << "\n";
    return 0;
}

static int cmd_append(const std::string &target) {
    std::string data = stdin_all();
    std::ofstream out(target, std::ios::app | std::ios::binary);
    out.write(data.data(), static_cast<std::streamsize>(data.size()));
    return out ? 0 : 2;
}

static int cmd_validate(const fs::path &root, const std::string &target) {
    fs::path resolved;
    if (!confined(root, target, resolved)) { std::cout << "BLOCKED\n"; return 0; }
    std::cout << "OK " << resolved.string() << "\n";
    return 0;
}

static int cmd_bench(const fs::path &root, const std::string &pattern, int rounds) {
    auto t0 = std::chrono::steady_clock::now();
    size_t hits = 0;
    for (int i = 0; i < rounds; ++i) {
        std::regex re(pattern);
        for (const auto &p : files(root)) {
            if (std::regex_search(read_file(p), re)) ++hits;
        }
    }
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - t0).count();
    std::cout << "rounds=" << rounds << " hits=" << hits << " ms=" << ms << "\n";
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "usage: qc_core <glob|grep|read|write|edit|list|hash|append|validate|bench> ...\n";
        return 1;
    }
    std::string cmd = argv[1];
    if (cmd == "append") {
        if (argc < 3) return 1;
        return cmd_append(argv[2]);
    }
    if (argc < 3) { std::cerr << "root required\n"; return 1; }
    fs::path root = argv[2];
    std::error_code ec;
    if (!fs::is_directory(root, ec)) { std::cerr << "not a directory: " << root.string() << "\n"; return 2; }
    if (cmd == "glob") return cmd_glob(root, argc > 3 ? argv[3] : "*", argc > 4 ? std::stoul(argv[4]) : 1000);
    if (cmd == "grep") return cmd_grep(root, argc > 3 ? argv[3] : "", argc > 4 ? argv[4] : "*", argc > 5 ? std::stoul(argv[5]) : 200);
    if (cmd == "read") return cmd_read(root, argc > 3 ? argv[3] : "", argc > 4 ? std::stoul(argv[4]) : 0, argc > 5 ? std::stoul(argv[5]) : 2000);
    if (cmd == "write") return cmd_write(root, argc > 3 ? argv[3] : "");
    if (cmd == "edit") return cmd_edit(root, argc > 3 ? argv[3] : "", argc > 4 ? argv[4] : "", argc > 5 ? argv[5] : "", argc > 6 ? std::string(argv[6]) == "1" : false);
    if (cmd == "list") return cmd_list(root, argc > 3 ? argv[3] : ".");
    if (cmd == "hash") return cmd_hash(root, argc > 3 ? argv[3] : "");
    if (cmd == "validate") return cmd_validate(root, argc > 3 ? argv[3] : "");
    if (cmd == "bench") return cmd_bench(root, argc > 3 ? argv[3] : "quillan", argc > 4 ? std::stoi(argv[4]) : 3);
    std::cerr << "unknown command: " << cmd << "\n";
    return 1;
}
