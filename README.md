# Visual Macro Automation

A Windows desktop MVP that watches the screen for configured image templates and runs mouse/keyboard macros when a match appears. It uses OpenCV for matching, MSS for capture, PySide6 for the GUI, and PyAutoGUI for optional input.

## Installation

Requires Windows and Python 3.11 or newer. From PowerShell in the project directory:

```powershell
python -m pip install -e ".[test]"
```

Launch the GUI with:

```powershell
python main.py
```

Or, after installing, use `visual-macro`.

## Usage

1. Click **Add Rule** and choose a small image crop to recognize.
2. In **Recognition**, set the confidence threshold as a percentage. Higher thresholds require a closer visual match. Optionally expand the screen-region controls and enter the left/top coordinates and width/height.
3. Add steps in **Actions**. Use the visual builder to add, edit, duplicate, remove, and reorder actions:
   - Click the detected template center, with button and click count.
   - Click relative to the detected template center using signed X/Y pixel offsets.
   - Click at fixed absolute screen coordinates, with button and click count.
   - Press a key.
   - Wait for a duration.
4. Click **Select Region…** to draw the search area on the desktop. The advanced coordinate fields remain available; they use pixels relative to the captured virtual-desktop image. **Capture Template…** is separate: select an image crop, preview it, and save it as the rule's template.
5. In **Trigger Behavior**, set the cooldown and whether the rule can repeat while the image stays visible.
6. Select a rule and click **Test Rule** to capture once, report match confidence/location (or the best confidence if absent), and preview its planned actions. A test never sends input, even when live mode is selected.
7. Keep **Simulation mode** enabled (the default) to log planned actions without sending input. The mode indicator turns red and warns that mouse/keyboard input will be sent when live mode is selected.
8. Click **Start** to monitor at the configured capture interval (default: 1 second), or **Stop** to stop. The status indicator reports Stopped, Running, or Error. Stopping takes effect between capture/matching steps or macro actions.
9. Use the profile toolbar or **Profile** menu to save/load settings and JSON profiles. Template paths inside saved profiles are relative when possible.

The activity log can be collapsed without losing its contents. A rule triggers on an absent-to-present transition; it must disappear before another trigger unless repeat is enabled. Repeat rules may trigger again after their cooldown while the match remains present.

## Profile format

Profiles use version 1 JSON. A minimal example:

```json
{
  "version": 1,
  "interval": 1.0,
  "simulation": true,
  "rules": [
    {
      "id": "example",
      "name": "Example",
      "template_path": "images/example.png",
      "threshold": 0.85,
      "region": null,
      "cooldown": 2.0,
      "repeat": false,
      "enabled": true,
      "actions": [
        {"type": "click", "x": 100, "y": 200, "button": "left", "clicks": 1},
        {"type": "delay", "seconds": 0.25},
        {"type": "press", "key": "enter"}
      ]
    }
  ]
}
```

The application validates profile values, action types, unique rule IDs, region geometry, and template availability before monitoring. An unreadable or missing image and invalid actions are reported in the activity log.

### Existing configuration and Python interfaces

Saved profile version 1 remains unchanged. The root contains `version`, `interval`, `simulation`, and `rules`. Each rule stores `id`, `name`, `template_path`, `threshold` (0–1), `region` (null or `[x, y, width, height]`), `cooldown`, `repeat`, `enabled`, and `actions`. Existing action objects remain:

```json
{"type": "click", "x": 100, "y": 200, "button": "left", "clicks": 1}
{"type": "click_center", "button": "left", "clicks": 1}
{"type": "click_offset", "offset_x": -10, "offset_y": 5, "button": "right", "clicks": 1}
{"type": "press", "key": "enter"}
{"type": "delay", "seconds": 0.5}
```

The new relative actions are additive; all existing fixed-click, key, and delay profile actions remain valid. Relative clicks require a matched template rectangle. The matcher retains the legacy frame-relative `Detection.location` and also supplies `Detection.bbox` as a physical screen-space `(x, y, width, height)` rectangle. The macro executor accepts the optional `detection_rect` argument; existing `execute(actions)` callers and fixed-coordinate click behavior remain unchanged. Simulation logs the calculated physical click point.

On Windows, the application requests per-monitor DPI awareness before creating the Qt application. Region selection maps Qt's per-screen logical coordinates to MSS physical desktop pixels, including negative monitor origins; region values are then converted back to the existing frame-relative JSON coordinates. Mixed-DPI monitors and actual mouse injection should be verified on the target desktop.

## Tests

Run the automated suite with:

```powershell
python -m pytest
```

## Limitations and troubleshooting

- Template matching is pixel-based; choose a crop that is distinctive and at the same scale and appearance as it will have on screen. Animations, scaling, theme changes, and overlays can reduce confidence.
- Regions use coordinates in the captured virtual-screen image, with the origin at its top-left. A region must fit within the captured screen.
- Capturing and controlling the desktop requires an interactive Windows session. A locked desktop, secure prompt, or disconnected remote session may prevent reliable capture/input.
- PyAutoGUI may be blocked by Windows permissions or security software. Test in simulation first, then enable real input only when you trust the configured actions. PyAutoGUI's fail-safe behavior remains enabled.
- Long configured delays are interruptible when stopping the worker. A currently executing system input call must return before shutdown finishes.
- If no match is reported, try a tighter template crop, check the configured region, and lower the confidence threshold gradually. If startup reports an image error, verify the template path and image format.
- Run the tests without a desktop using `python -m pytest`; actual capture, real input, and visual match quality require manual testing in an interactive Windows session.
