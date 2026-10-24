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

1. Click **Add Template…** and select a small image crop to recognize.
2. Set the confidence threshold (0–1), optional screen region (`x,y,width,height`), cooldown, and whether the rule may repeat while its image stays visible.
3. Enter macro actions as a JSON array. Supported actions:
   - `{"type":"click","x":100,"y":200,"button":"left","clicks":1}`
   - `{"type":"press","key":"enter"}`
   - `{"type":"delay","seconds":0.5}`
4. Select a rule and click **Test Rule** to capture the screen once and test its macro.
5. Keep **Simulation mode** checked (the default) to log planned actions without sending input. Uncheck it only when ready to let PyAutoGUI control the desktop.
6. Click **Start** to monitor at the configured capture interval (default: 1 second), or **Stop** to end monitoring.
7. Use **Save Profile** and **Load Profile…** to store or restore rules and settings in JSON. Template paths inside the profile are relative when possible.

The activity log includes match locations and confidence scores, planned or executed actions, and errors. A rule triggers on an absent-to-present transition; it must disappear before another trigger unless repeat is enabled. Repeat rules may trigger again after their cooldown while the match remains present.

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
