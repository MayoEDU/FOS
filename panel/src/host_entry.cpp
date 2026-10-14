// Typing the target PC's IPv4 address on the panel's keypad.
#include "host_entry.h"

namespace host_entry {

HostError checkHost(const std::string& text) {
    if (text.empty()) return HostError::Empty;
    // Four numbers 0-255 of 1-3 digits, separated by dots
    int parts = 0;
    size_t start = 0;
    while (true) {
        const size_t dot = text.find('.', start);
        const std::string part = text.substr(start, dot == std::string::npos ? std::string::npos : dot - start);
        // A leading zero is refused: the address lookup reads "010" as octal (8), so it would send elsewhere
        if (part.empty() || part.size() > 3 || part.find_first_not_of("0123456789") != std::string::npos ||
            (part.size() > 1 && part[0] == '0') || std::stoi(part) > 255) {
            return HostError::Ipv4;
        }
        ++parts;
        if (dot == std::string::npos) break;
        start = dot + 1;
    }
    return parts == 4 ? HostError::None : HostError::Ipv4;
}

std::string keypadInput(const std::string& text, int key) {
    if (key == kBackspace) return text.empty() ? text : text.substr(0, text.size() - 1);
    const bool digit = key >= '0' && key <= '9';
    if ((!digit && key != '.') || text.size() >= kKeypadMax) return text;
    return text + static_cast<char>(key);
}

}  // namespace host_entry
