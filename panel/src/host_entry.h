// Typing the target PC's IPv4 address on the panel's keypad (the Basic tab's "Enter IP"): the keypad's editing and
// checking what was typed. A host name can only be set in config.json. Nothing here draws or talks to OpenVR, so it
// is tested on its own (text_test.cpp).
#pragma once

#include <string>

namespace host_entry {

/** What is wrong with a typed address. */
enum class HostError {
    None,   ///< an IPv4 address
    Empty,  ///< nothing typed
    Ipv4,   ///< not four numbers 0-255 separated by dots
};

/** The keypad's backspace key (the others are '0'-'9' and '.'). */
constexpr int kBackspace = 8;
/** The keypad takes at most this many characters ("255.255.255.255"). */
constexpr size_t kKeypadMax = 15;

/**
 * Check a typed address.
 * @param text what was typed
 * @return what is wrong, or HostError::None
 * @example
 * checkHost("192.168.1.20") // HostError::None
 * checkHost("192.168.1") // HostError::Ipv4
 */
HostError checkHost(const std::string& text);

/**
 * One keypad press.
 * @param text the text so far
 * @param key '0'-'9', '.' or kBackspace
 * @return the new text (unchanged if the key does not fit)
 */
std::string keypadInput(const std::string& text, int key);

}  // namespace host_entry
