"""Utility functions for libclang detection and helpers."""

import os
import sys
import platform
import glob


def find_libclang():
    """Attempt to find and configure libclang. Returns True if successful."""
    try:
        from clang.cindex import Index, Config
        
        try:
            Index.create()
            return True
        except Exception:
            pass
        
        search_paths = []
        
        if platform.system() == "Windows":
            search_paths = [
                os.path.join(sys.prefix, "Library", "bin"),
                os.path.join(sys.prefix, "bin"),
                os.path.join(os.environ.get("CONDA_PREFIX", ""), "Library", "bin"),
                os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin"),
                os.path.expandvars(r"%ProgramFiles%\LLVM\bin"),
                os.path.expandvars(r"%ProgramFiles(x86)%\LLVM\bin"),
                r"C:\Program Files\LLVM\bin",
                r"C:\Program Files (x86)\LLVM\bin",
                os.path.dirname(sys.executable),
            ]
            lib_name = "libclang.dll"
        else:
            search_paths = [
                "/usr/lib",
                "/usr/lib/x86_64-linux-gnu",
                "/usr/lib/aarch64-linux-gnu",
                "/usr/lib64",
                "/usr/local/lib",
                sys.prefix + "/lib",
                os.path.join(os.environ.get("CONDA_PREFIX", ""), "lib") if os.environ.get("CONDA_PREFIX") else "",
            ]
            lib_name = "libclang.so*"
        
        for base in search_paths:
            if not base:
                continue
            try:
                if platform.system() == "Windows":
                    dll_path = os.path.join(base, lib_name)
                    if os.path.isfile(dll_path):
                        Config.set_library_file(dll_path)
                        Index.create()
                        return True
                else:
                    matches = glob.glob(os.path.join(base, lib_name))
                    for path in matches:
                        if os.path.isfile(path):
                            Config.set_library_file(path)
                            Index.create()
                            return True
            except Exception:
                continue
        
        try:
            import clang
            pkg_path = os.path.dirname(clang.__file__)
            native_path = os.path.join(pkg_path, "native")
            if platform.system() == "Windows":
                dll = os.path.join(native_path, "libclang.dll")
                if os.path.isfile(dll):
                    Config.set_library_file(dll)
                    Index.create()
                    return True
            else:
                for f in os.listdir(native_path or []):
                    if "libclang" in f and f.endswith(".so"):
                        Config.set_library_file(os.path.join(native_path, f))
                        Index.create()
                        return True
        except Exception:
            pass
        
        return False
    except ImportError:
        return False


def get_lines_context(source: str, line_num: int, context_lines: int = 1) -> tuple:
    """Get lines before, at, and after the error line."""
    lines = source.splitlines()
    total = len(lines)
    start = max(0, line_num - 1 - context_lines)
    end = min(total, line_num + context_lines)
    
    before = []
    error_line = ""
    after = []
    
    for i in range(start, end):
        content = lines[i] if i < total else ""
        num = i + 1
        if num < line_num:
            before.append((num, content))
        elif num == line_num:
            error_line = content
        else:
            after.append((num, content))
    
    return before, error_line, after
