#pragma once

#include <stddef.h>

namespace WirelessStream {
bool begin();
void service(const char* statusLine);
void publish(const char* line, size_t length);
void publish(const char* line);
bool available();
bool connected();
}
