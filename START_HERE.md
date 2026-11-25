# EPL428 Gesture Recognition with One LilyGO

The LilyGO T-Beam S3 Supreme uses its QMI8658 accelerometer and gyroscope to identify three classes: **rest, gentle rotation and side-to-side movement**. The board runs the classifier and shows its output on the OLED. The PC records labeled samples over USB and trains and evaluates the model. The firmware reuses the board, sensor and display setup from EPL428 LAB03.

## 1. Connect and check the board

Follow the lab handout for antenna and power setup. Connect the LilyGO directly with a USB data cable. Open the folder containing `platformio.ini` in VS Code. PlatformIO should use the `t-beams3-supreme` environment and the single active source directory `student/05_Project`.

Open PowerShell in the project folder and identify the board's serial port.

```powershell
.\.venv\Scripts\python.exe .\pc\capture.py --list
```

Build and upload with PlatformIO using the port verified above. In the commands below, replace `BOARD_PORT` with that port. Close Serial Monitor before starting any Python command that reads the board.

```powershell
.\.venv\Scripts\python.exe .\pc\capture.py --port BOARD_PORT --check
```

The diagnostic records PMU, IMU and OLED initialization, eight seconds of serial traffic and the median interval between samples in `data/checks`. In Serial Monitor at **115200**, `?` requests `STATUS,imu1,model_id,pmu,imu,oled`. The untrained capture firmware emits `RESULT,-1,timestamp_ms`. Check the display in person for `EPL428 / IMU`, `NO TRAINED MODEL` and the sample counter.

If Windows lists no port, reconnect the board directly with a known USB data cable and try another USB port. If a port still does not appear, hold **BOOT**, tap **RST**, release **BOOT**, and check the list again. This enters download mode for uploading. [LilyGO T-Beam Supreme FAQ](https://wiki.lilygo.cc/products/t-beam-series/t-beam-supreme/#faq)

If the IMU works and the OLED is blank, continue data collection over USB and record the OLED issue for the lab. A serial status flag confirms initialization only. Verify visible text before the demo.

## 2. Record labeled sessions

Collect **six independent sessions** as the initial target, with 30 seconds per gesture. The training program accepts at least four valid sessions. Reserve the final complete session for testing. Pass `--sessions` to run several guided sessions from one command. Omit it to record one session.

```powershell
.\.venv\Scripts\python.exe .\pc\capture.py --port BOARD_PORT --sessions 6
```

| Class | Gesture |
| --- | --- |
| `rest` | Hold the board still and level. |
| `rotation` | Turn gently left and right around the same point. |
| `translation` | Move from side to side while keeping the board's orientation. |

Keep some slack in the cable and perform each gesture throughout the recording. The LAB03 gyroscope range is ±64°/s, so turn slowly. Set the board down between takes and pick it up again. Record at least one take later to introduce normal variation. Each session should come from a fresh recording.

The script saves three CSV files, serial logs and `session.json` under `data/raw/<session_id>`. Acceleration is measured in g, angular velocity in degrees per second, and timestamps in milliseconds since boot. If you perform the wrong gesture or interrupt a take, preserve the records. Set `status` to `invalid` in `session.json` for a mislabeled session. Interrupted sessions remain `incomplete`.

If a gesture stops because the serial stream is interrupted but the port stays available, the recorder keeps the partial take in `interrupted/` and prompts you to repeat that gesture. Completed gestures remain saved. If capture exits after a disconnect, use `--list` to find the board again and start a fresh session.

## 3. Train and evaluate the classifier

```powershell
.\.venv\Scripts\python.exe .\pc\training.py --export
```

The trainer groups consecutive data into windows of 100 samples and computes the mean and population standard deviation of each of the six axes. A gap over 100 ms clears a partial window. The actual window duration depends on the measured sampling rate.

It compares a most-frequent-class baseline and decision trees with depth limits of 2, 3, 4 and 5. It holds out one training session per validation fold and chooses the tree with the best mean macro F1, favoring a shallower tree on a tie. It then reports accuracy, macro F1 and a confusion matrix on the reserved test session. By default the last valid UTC-named session is the test. Use `--test-session SESSION_ID` for a manually named holdout.

Each run writes a manifest, metrics, plots and a copy of `Model.h` to `results/<training_id>`. The `--export` flag also installs the header in the firmware. If the test results influence any change to the model or gesture protocol, collect a new test session for the revised design.

## 4. Verify the model on the board

Build and upload again after exporting the trained model. The OLED should show `MODEL READY` and the latest label. Close Serial Monitor and run the following command with the ID printed by the trainer.

```powershell
.\.venv\Scripts\python.exe .\pc\demo.py --port BOARD_PORT --run TRAINING_ID
```

Perform each prompted gesture for 12 seconds and observe the OLED. The script checks the model ID and matches each serial prediction to its sample window. It saves the prediction counts, measured window spans and your OLED observations in `data/demo/<demo_id>/demo.json` alongside the logs. Save a photo or video of the display there. Report these live results separately from the held-out test. The measured span of a window is distinct from the time it takes a new gesture to appear on screen.

## 5. Play Orbit Maze

Orbit Maze uses the model running on the LilyGO. Close Serial Monitor, the recorder and the demo before launching the game, so it can open the serial port. The game looks for the board over USB and reconnects if it becomes available again. Use `--port BOARD_PORT` to select a specific board.

```powershell
.\.venv\Scripts\python.exe .\pc\maze.py
```

Hold the board still and level, OLED facing up, until **Ready** appears. From the main menu:

| Gesture | Menu action | Keyboard shortcut |
| --- | --- | --- |
| Slide sideways | Start or continue | F or Enter |
| Turn right | Save the journey locally | R |
| Turn left | Exit the game | Q |

In the maze, **turn left or right** to rotate the arrow 90° in that direction, and **slide** to move one tile along the arrow. The device indicator shows **Reading gesture** while the game measures the motion. The status panel shows the last accepted input and any obstacle that blocked the move. Rest briefly until **Ready** returns. **Tilt up and hold** to open the menu, or press **Esc**. The game combines the signed angle of a short rotation with lateral acceleration after correcting for the board's tilt. It can establish its initial reference from a model rest prediction or a sustained level hold measured by the IMU. The OLED shows the board's full-window prediction.

The route visits **Pafos**, **Limasol** and **Nicosia**, in that order. Pafos opens with a controls tutorial. Collect a key to open the exit in each city, then slide again to advance. In Nicosia, watch the moving lantern on the marked tiles. It sends you back to the entrance if it catches you, and you keep the key. Saving preserves the current city, position, arrow and key. The save stays on this PC in `data/orbit_save.json`.

The original artwork is inspired by [Pafos Harbour and its mosaics](https://www.visitcyprus.com/discover-cyprus/regions-cities/pafos-regions-cities/pafos-paphos-city/), [the Molos seafront and marina](https://www.visitcyprus.com/wp-content/uploads/files/MAPS/CITY_TOUR_MAPS/Limassol_Map.pdf), and [Nicosia's Venetian walls and Famagusta Gate](https://www.nicosia.org.cy/en-GB/discover/cultural-centers/famagusta-gate/).

Use the keyboard to practise while recording or before a model is installed. This mode leaves the serial port free.

```powershell
.\.venv\Scripts\python.exe .\pc\maze.py --keyboard
```

Press **Q** to turn left, **R** to turn right and **F** to move. This mode uses the Tk support already present in the local Python environment.

### Calibrate single game gestures

If slides and turns are confused, save and close the game first. Record fifteen short trials, one gesture after each `GO` cue. Use the port shown by `capture.py --list`.

```powershell
.\.venv\Scripts\python.exe .\pc\calibrate_game.py --port BOARD_PORT
.\.venv\Scripts\python.exe .\pc\fit_game_profile.py PATH_TO_CALIBRATION_SESSION --apply
```

To finish an interrupted recording, run `calibrate_game.py --resume PATH_TO_CALIBRATION_SESSION` with the same Python executable. The recorder waits for the LilyGO over USB if `--port` is omitted and starts at the next unsaved trial.

The fitter uses nine trials to prioritize correct gestures and then reduce decision time. It measures time from the detected motion onset to the command. It checks the selected settings and the current profile against the same six separate trials. Installation requires at least five correct responses, zero incorrect or extra actions, and at least as many correct responses as the current profile. Reopen the game to load the profile.

## 6. Finish the submission

The instructor's 6 November update gives **29 November 2026** as the submission date, an **up to five-page report**, **five slides for five minutes**, and **code and data on GitHub**. The live demos are planned for the last two classes. Check the class announcement for the submission channel, time and demo slot.

See [the Orbit Maze project report](report/EPL428%20Orbit%20Maze%20Report.docx) for the real dataset totals, validation comparison, test confusion matrix and live board results. Be ready to explain the sensor signals, window features, decision tree, session split and what the results cover.

| Path | Purpose |
| --- | --- |
| `student/05_Project` | Arduino firmware, feature calculation and model header. |
| `pc/capture.py` | Device check and guided data collection. |
| `pc/motion_data.py` | Recording validation and feature extraction. |
| `pc/training.py` | Model comparison, evaluation and C++ export. |
| `pc/demo.py` | On-board model and OLED evidence. |
| `pc/maze.py`, `pc/maze_app.py`, `pc/maze_art.py`, `pc/maze_logic.py`, `pc/game_input.py` | Play and save Orbit Maze with the LilyGO's USB predictions and sensor data, or the keyboard. |
| `boards`, `lib`, `PROVENANCE.json` | Versioned LAB03 board definition and libraries with source hashes. |

This PC already has the project's Python environment. To reproduce it on another Windows PC with Python 3.12, run the following commands. Use the pinned PlatformIO environment in the project configuration.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```
