import ast

def analyze_code():
    with open("wx_app.py", "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    issues = []

    # 1. Find all class methods and track assigned attributes vs accessed attributes
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.classes = {}
            self.current_class = None
            self.current_method = None

        def visit_ClassDef(self, node):
            self.current_class = node.name
            self.classes[node.name] = {"assigned": set(), "accessed": set()}
            self.generic_visit(node)
            self.current_class = None

        def visit_FunctionDef(self, node):
            self.current_method = node.name
            self.generic_visit(node)
            self.current_method = None

        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "self" and self.current_class:
                # Is it assignment?
                # We can roughly guess by context, but for now just collect all accessed.
                # A more thorough check is to inspect the parent node.
                pass
            self.generic_visit(node)

    # Let's do a simple regex/string based check for thread-safety and missing attributes
    import re
    
    methods_code = {}
    current_method = None
    lines = source.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r'^    def (\w+)\(self', line)
        if m:
            current_method = m.group(1)
            methods_code[current_method] = []
        elif current_method and line.startswith("        "):
            methods_code[current_method].append((i+1, line))
        elif line.strip() == "" or line.startswith("    #"):
            if current_method:
                methods_code[current_method].append((i+1, line))
        else:
            if line.startswith("    ") and not line.startswith("        ") and "def " not in line:
                pass
            else:
                current_method = None

    workers = ["_run_thread_custom", "_GenAutoWorker", "_GenDesignWorker", "_SavePresetWorker", "_CloneWorker", "DoHeavyImports"]
    
    for worker in workers:
        if worker in methods_code:
            for line_num, line in methods_code[worker]:
                if "wx." in line and "wx.CallAfter" not in line and "op_dialog.cancel_flag" not in line:
                    if "wx.MessageBox" in line or "SetLabel" in line or "SetValue" in line:
                        issues.append(f"Line {line_num} in {worker}: Potential thread-safety issue: {line.strip()}")

    # Collect all self. assignments
    assigned = set()
    for i, line in enumerate(lines):
        m = re.findall(r'self\.([a-zA-Z0-9_]+)\s*=', line)
        for match in m:
            assigned.add(match)
            
    # Check all self. accesses
    for i, line in enumerate(lines):
        m = re.findall(r'self\.([a-zA-Z0-9_]+)', line)
        for match in m:
            if match not in assigned and match not in ["cfg", "Log", "RefreshPresets", "current_op", "gauge", "EndModal", "GetParent", "_CheckDeleteWarning", "SaveConfig", "dialog", "Centre", "ShowModal", "Destroy", "is_first_run", "avail_langs", "SetTitle", "Bind", "Layout", "Show", "GetMenuBar", "Close", "EndOperation", "RunOperation", "GetGenConfig", "audio_data", "sample_rate", "_", "panel", "main_vbox", "btn_stop", "prog_timer", "btn_gen_clone", "btn_gen_design", "btn_save_preset", "model", "BrowseFor", "TogglePlayFile", "ToggleRecord", "status_text"]:
                # Filter out standard wx methods and our known methods
                if match not in ["SetSizer", "Refresh", "Update", "GetSize", "SetSize", "Maximize", "Iconize", "GetPosition", "SetPosition", "Hide", "Enable", "Disable", "GetLabel", "SetLabel", "GetValue", "SetValue", "GetSelection", "SetSelection", "GetClientData", "SetClientData", "Clear", "Append", "GetCount", "GetString", "SetString", "SetFocus", "HasFocus", "GetId", "SetId", "GetName", "SetName", "GetToolTip", "SetToolTip", "GetChildren", "GetParent", "GetTopLevelParent", "GetEventHandler", "SetEventHandler", "GetEvtHandlerEnabled", "SetEvtHandlerEnabled", "GetNextHandler", "SetNextHandler", "GetPreviousHandler", "SetPreviousHandler", "GetClientObject", "SetClientObject", "GetValidator", "SetValidator", "GetDropTarget", "SetDropTarget", "GetWindowStyleFlag", "SetWindowStyleFlag", "GetWindowStyle", "SetWindowStyle", "GetExtraStyle", "SetExtraStyle", "GetBackgroundColour", "SetBackgroundColour", "GetForegroundColour", "SetForegroundColour", "GetFont", "SetFont", "GetCursor", "SetCursor", "GetCaret", "SetCaret", "GetCharHeight", "GetCharWidth", "GetTextExtent", "GetClientSize", "SetClientSize", "GetRect", "SetRect", "GetScreenPosition", "SetScreenPosition", "GetScreenRect", "ClientToScreen", "ScreenToClient", "HitTest", "GetUpdateRegion", "GetUpdateClientRect", "IsExposed", "GetBestSize", "GetMinSize", "GetMaxSize", "SetMinSize", "SetMaxSize", "GetSizeHints", "SetSizeHints", "GetVirtualSize", "SetVirtualSize", "GetBestVirtualSize", "GetWindowVariant", "SetWindowVariant", "GetBackgroundStyle", "SetBackgroundStyle", "GetLabelText", "GetHelpText", "SetHelpText", "GetToolTipText", "SetToolTipText"]:
                    if match not in ["SetupCloneTab", "SetupDesignTab", "SetupAdvTab", "SetupAutoTab", "OnBrowseRefAudio", "OnSavePresetPrompt", "OnDelPreset", "OnDelAllPresets", "OnPresetKeyDown", "OnGenClone", "OnGenDesign", "OnGenAuto", "OnPlayAudio", "OnSaveAudio", "OnStopOperation", "OnToggleModel", "OnShowTags", "OnResetApp", "OnCleanTemp", "AutoLoadModel", "InitUI", "CreateMenu", "HandleCancel", "Worker", "InitSystem"]:
                        issues.append(f"Line {i+1}: Possible uninitialized attribute access: self.{match}")

    with open("audit_results.txt", "w", encoding="utf-8") as f:
        for iss in issues:
            f.write(iss + "\n")
            
analyze_code()
