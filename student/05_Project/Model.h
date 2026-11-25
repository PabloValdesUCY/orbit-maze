#pragma once

// Decision tree from training run 20261123T144139418921Z.
static constexpr bool MODEL_TRAINED = true;
static constexpr const char* MODEL_RUN_ID = "20261123T144139418921Z";
static constexpr const char* MODEL_LABELS[3] = {"rest", "rotation", "translation"};

inline int predictMotion(const float features[12]) {
    // std_gz_dps
    if (static_cast<double>(features[11]) <= 0.12084539979696274) {
        return 0;  // rest
    } else {
        // std_ay_g
        if (static_cast<double>(features[7]) <= 0.0024394497741013765) {
            // std_gz_dps
            if (static_cast<double>(features[11]) <= 1.770153820514679) {
                return 2;  // translation
            } else {
                return 1;  // rotation
            }
        } else {
            // std_gz_dps
            if (static_cast<double>(features[11]) <= 4.322850584983826) {
                return 2;  // translation
            } else {
                return 1;  // rotation
            }
        }
    }
}
