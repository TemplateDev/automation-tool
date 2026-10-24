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

## Managed application data

On Windows, application data is stored under `%LOCALAPPDATA%\VisualMacroAutomation` (falling back to `%APPDATA%` if needed). It contains:

- `templates/` — validated imported images and captured templates with unique filenames derived from their friendly names.
- `profiles/` — the suggested location for new profiles; profiles saved here refer to managed templates with stable relative paths.
- `logs/activity.log` — persistent application activity.
- `settings.json` — application settings and the last successfully loaded/saved profile path for restart recovery.

Captured templates are previewed and confirmed before being saved, and are saved directly in `templates/` without a filesystem-path prompt. **Import Image…** separately copies and validates an external image into managed storage. Existing profiles with absolute template paths continue to load; loading them does not copy, move, or delete their source files. Missing last-used profiles and unreadable settings are reported without deleting or replacing user data. The non-Windows development fallback is `$XDG_DATA_HOME/visual-macro-automation` or `~/.local/share/visual-macro-automation`.

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

## Manual validation checklist

These checks require an interactive Windows desktop. They have **not been run automatically or manually in this environment**; record results on the target machine:

- [ ] Move and resize the application while monitoring; confirm controls, thumbnails, and activity log remain usable.
- [ ] On each display-scaling setting and with monitors on both sides of the primary (including a negative-origin monitor), select a region and compare displayed coordinates/dimensions with the intended physical pixels.
- [ ] Test two similar-looking icons, then partially occlude each; verify thresholds avoid unintended triggers and observe confidence/location logs.
- [ ] Make a template appear and disappear faster than the capture interval; verify the expected sampling/trigger behavior and repeat/cooldown semantics.
- [ ] Capture and import templates, save multiple profiles, restart the application, and verify managed files and the last profile recover without moving/deleting source images.
- [ ] Stop during a long wait and during a multi-action macro; verify no later action runs after the current in-progress OS input returns.
- [ ] Close the application during monitoring and confirm it exits cleanly without leaving an active worker.
- [ ] Keep simulation mode enabled for dry runs. Only separately verify live clicks on a harmless target after confirming the simulated coordinates.

## Limitations and troubleshooting

- Template matching is pixel-based; choose a crop that is distinctive and at the same scale and appearance as it will have on screen. Animations, scaling, theme changes, and overlays can reduce confidence.
- Regions use coordinates in the captured virtual-screen image, with the origin at its top-left. A region must fit within the captured screen.
- Capturing and controlling the desktop requires an interactive Windows session. A locked desktop, secure prompt, or disconnected remote session may prevent reliable capture/input.
- PyAutoGUI may be blocked by Windows permissions or security software. Test in simulation first, then enable real input only when you trust the configured actions. PyAutoGUI's fail-safe behavior remains enabled.
- Long configured delays are interruptible when stopping the worker. A currently executing system input call must return before shutdown finishes.
- If no match is reported, try a tighter template crop, check the configured region, and lower the confidence threshold gradually. If startup reports an image error, verify the template path and image format.
- Run the tests without a desktop using `python -m pytest`; actual capture, real input, and visual match quality require manual testing in an interactive Windows session.
- Mixed-DPI physical coordinate mapping is covered by synthetic automated cases but still needs validation on the actual monitor arrangement. Persistent storage write failures are reported in the activity panel; check permissions and available disk space under the app-data directory.
