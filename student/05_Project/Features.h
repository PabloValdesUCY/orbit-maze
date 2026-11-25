#pragma once

#include <cmath>
#include <stdint.h>

constexpr uint8_t MOTION_CHANNEL_COUNT = 6;
constexpr uint8_t MOTION_FEATURE_COUNT = 12;
constexpr uint8_t MOTION_WINDOW_SIZE = 100;
constexpr uint32_t MOTION_MAX_GAP_MS = 100;

class MotionWindow {
public:
    uint8_t count() const { return count_; }
    bool hasSample() const { return hasSample_; }

    bool hasGap(uint32_t timestamp) const {
        return hasSample_ && static_cast<uint32_t>(timestamp - lastTimestamp_) > MOTION_MAX_GAP_MS;
    }

    void reset() {
        clearSums();
        hasSample_ = false;
    }

    // Input order is ax, ay, az, gx, gy, gz. Returns true when a window is complete.
    bool add(uint32_t timestamp, const float sample[MOTION_CHANNEL_COUNT],
             float features[MOTION_FEATURE_COUNT]) {
        if (hasGap(timestamp)) reset();
        lastTimestamp_ = timestamp;
        hasSample_ = true;

        for (uint8_t channel = 0; channel < MOTION_CHANNEL_COUNT; ++channel) {
            const float value = sample[channel];
            // Match Python's float32 rounding after each operation.
            const volatile float square = value * value;
            sums_[channel] += value;
            squaredSums_[channel] += square;
        }
        ++count_;
        if (count_ < MOTION_WINDOW_SIZE) return false;

        for (uint8_t channel = 0; channel < MOTION_CHANNEL_COUNT; ++channel) {
            const float mean = sums_[channel] / MOTION_WINDOW_SIZE;
            const volatile float meanSquared = mean * mean;
            const float variance = squaredSums_[channel] / MOTION_WINDOW_SIZE - meanSquared;
            features[channel] = mean;
            features[MOTION_CHANNEL_COUNT + channel] = std::sqrt(variance > 0.0f ? variance : 0.0f);
        }
        clearSums();
        return true;
    }

private:
    void clearSums() {
        for (uint8_t channel = 0; channel < MOTION_CHANNEL_COUNT; ++channel) {
            sums_[channel] = 0.0f;
            squaredSums_[channel] = 0.0f;
        }
        count_ = 0;
    }

    float sums_[MOTION_CHANNEL_COUNT] = {};
    float squaredSums_[MOTION_CHANNEL_COUNT] = {};
    uint32_t lastTimestamp_ = 0;
    uint8_t count_ = 0;
    bool hasSample_ = false;
};
