from __future__ import annotations

import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from libs import github_library, source_path, write_source_text
from tools import ensure_tool, get_pcbuild_output_dir, run


GLFW_VERSION = "3.4"
GLFW_PROJECT_GUID = "{F2F8F2AC-6295-4EC2-A9C4-95CF64F0A9B2}"
GLFW_STATIC_LIBRARY = "glfw3.lib"
GLFW_SYSTEM_LIBRARIES = [
    "opengl32.lib",
    "gdi32.lib",
    "user32.lib",
    "shell32.lib",
    "advapi32.lib",
    "ole32.lib",
    "imm32.lib",
    "winmm.lib",
    "version.lib",
    "setupapi.lib",
    "dwmapi.lib",
]


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def glfw_source_root(context) -> Path:
    return source_path(context, f"glfw_builtin/glfw-{GLFW_VERSION}")


def glfw_build_dir(context) -> Path:
    return (
        context.work_cache_root
        / "glfw"
        / context.version_full
        / context.source_root.name
        / f"{GLFW_VERSION}-{context.platform}-{context.configuration}"
    )


def _render_glfw_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{GLFW_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>glfw__glfw</RootNamespace>
    <Keyword>Win32Proj</Keyword>
    <SupportPGO>false</SupportPGO>
    <WindowsTargetPlatformVersion>$(DefaultWindowsSDKVersion)</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="python.props" />
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
    <CharacterSet>Unicode</CharacterSet>
    <PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
    <Import Project="pyproject.props" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup>
    <TargetName>glfw._glfw</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\glfw_builtin\\glfw-{GLFW_VERSION}\\include;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;GLFW_INCLUDE_NONE;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4100;4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\glfw_builtin\\staticpython_glfw.c" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


GLFW_EXTENSION_SOURCE = r"""
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <GLFW/glfw3.h>

typedef struct {
    PyObject_HEAD
    GLFWwindow *window;
    PyObject *key_callback;
    PyObject *cursor_pos_callback;
    PyObject *window_size_callback;
    PyObject *char_callback;
    PyObject *scroll_callback;
    PyObject *mouse_button_callback;
    PyObject *window_close_callback;
} PyGLFWWindow;

static PyTypeObject PyGLFWWindow_Type;
static PyObject *error_callback = NULL;

static PyGLFWWindow *window_from_object(PyObject *obj) {
    if (!PyObject_TypeCheck(obj, &PyGLFWWindow_Type)) {
        PyErr_SetString(PyExc_TypeError, "expected a glfw window");
        return NULL;
    }
    PyGLFWWindow *window = (PyGLFWWindow *)obj;
    if (window->window == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "glfw window has been destroyed");
        return NULL;
    }
    return window;
}

static GLFWwindow *optional_window_pointer(PyObject *obj) {
    if (obj == Py_None) {
        return NULL;
    }
    PyGLFWWindow *window = window_from_object(obj);
    if (window == NULL) {
        return NULL;
    }
    return window->window;
}

static void PyGLFWWindow_dealloc(PyGLFWWindow *self) {
    if (self->window != NULL) {
        glfwSetWindowUserPointer(self->window, NULL);
        glfwDestroyWindow(self->window);
        self->window = NULL;
    }
    Py_XDECREF(self->key_callback);
    Py_XDECREF(self->cursor_pos_callback);
    Py_XDECREF(self->window_size_callback);
    Py_XDECREF(self->char_callback);
    Py_XDECREF(self->scroll_callback);
    Py_XDECREF(self->mouse_button_callback);
    Py_XDECREF(self->window_close_callback);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *PyGLFWWindow_repr(PyGLFWWindow *self) {
    return PyUnicode_FromFormat("<glfw.Window handle=%p>", self->window);
}

static PyTypeObject PyGLFWWindow_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
};

static PyObject *make_window(GLFWwindow *handle) {
    PyGLFWWindow *window = PyObject_New(PyGLFWWindow, &PyGLFWWindow_Type);
    if (window == NULL) {
        return NULL;
    }
    window->window = handle;
    window->key_callback = NULL;
    window->cursor_pos_callback = NULL;
    window->window_size_callback = NULL;
    window->char_callback = NULL;
    window->scroll_callback = NULL;
    window->mouse_button_callback = NULL;
    window->window_close_callback = NULL;
    glfwSetWindowUserPointer(handle, window);
    return (PyObject *)window;
}

static void call_callback(PyObject *callback, PyObject *args) {
    if (callback == NULL || callback == Py_None) {
        Py_XDECREF(args);
        return;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    if (args != NULL) {
        PyObject *result = PyObject_CallObject(callback, args);
        if (result == NULL) {
            PyErr_WriteUnraisable(callback);
        }
        Py_XDECREF(result);
    }
    Py_XDECREF(args);
    PyGILState_Release(gil);
}

static PyObject *callback_window(GLFWwindow *handle) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) {
        Py_RETURN_NONE;
    }
    Py_INCREF(window);
    return (PyObject *)window;
}

static void trampoline_error(int code, const char *description) {
    if (error_callback == NULL || error_callback == Py_None) {
        return;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *result = PyObject_CallFunction(error_callback, "is", code, description ? description : "");
    if (result == NULL) {
        PyErr_WriteUnraisable(error_callback);
    }
    Py_XDECREF(result);
    PyGILState_Release(gil);
}

static void trampoline_key(GLFWwindow *handle, int key, int scancode, int action, int mods) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->key_callback, Py_BuildValue("(Oiiii)", py_window, key, scancode, action, mods));
    Py_DECREF(py_window);
}

static void trampoline_cursor_pos(GLFWwindow *handle, double x, double y) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->cursor_pos_callback, Py_BuildValue("(Odd)", py_window, x, y));
    Py_DECREF(py_window);
}

static void trampoline_window_size(GLFWwindow *handle, int width, int height) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->window_size_callback, Py_BuildValue("(Oii)", py_window, width, height));
    Py_DECREF(py_window);
}

static void trampoline_char(GLFWwindow *handle, unsigned int codepoint) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->char_callback, Py_BuildValue("(OI)", py_window, codepoint));
    Py_DECREF(py_window);
}

static void trampoline_scroll(GLFWwindow *handle, double xoffset, double yoffset) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->scroll_callback, Py_BuildValue("(Odd)", py_window, xoffset, yoffset));
    Py_DECREF(py_window);
}

static void trampoline_mouse_button(GLFWwindow *handle, int button, int action, int mods) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->mouse_button_callback, Py_BuildValue("(Oiii)", py_window, button, action, mods));
    Py_DECREF(py_window);
}

static void trampoline_window_close(GLFWwindow *handle) {
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) return;
    PyObject *py_window = callback_window(handle);
    call_callback(window->window_close_callback, Py_BuildValue("(O)", py_window));
    Py_DECREF(py_window);
}

static PyObject *py_init(PyObject *self, PyObject *Py_UNUSED(args)) {
    return PyBool_FromLong(glfwInit());
}

static PyObject *py_terminate(PyObject *self, PyObject *Py_UNUSED(args)) {
    glfwTerminate();
    Py_RETURN_NONE;
}

static PyObject *py_window_hint(PyObject *self, PyObject *args) {
    int hint, value;
    if (!PyArg_ParseTuple(args, "ii", &hint, &value)) return NULL;
    glfwWindowHint(hint, value);
    Py_RETURN_NONE;
}

static PyObject *py_default_window_hints(PyObject *self, PyObject *Py_UNUSED(args)) {
    glfwDefaultWindowHints();
    Py_RETURN_NONE;
}

static PyObject *py_create_window(PyObject *self, PyObject *args) {
    int width, height;
    const char *title;
    PyObject *monitor_obj = Py_None;
    PyObject *share_obj = Py_None;
    if (!PyArg_ParseTuple(args, "iis|OO", &width, &height, &title, &monitor_obj, &share_obj)) return NULL;
    GLFWwindow *share = NULL;
    if (share_obj != Py_None) {
        PyGLFWWindow *share_window = window_from_object(share_obj);
        if (share_window == NULL) return NULL;
        share = share_window->window;
    }
    GLFWwindow *handle = glfwCreateWindow(width, height, title, NULL, share);
    if (handle == NULL) {
        Py_RETURN_NONE;
    }
    return make_window(handle);
}

static PyObject *py_destroy_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwSetWindowUserPointer(window->window, NULL);
    glfwDestroyWindow(window->window);
    window->window = NULL;
    Py_RETURN_NONE;
}

static PyObject *py_make_context_current(PyObject *self, PyObject *arg) {
    GLFWwindow *window = optional_window_pointer(arg);
    if (window == NULL && PyErr_Occurred()) return NULL;
    glfwMakeContextCurrent(window);
    Py_RETURN_NONE;
}

static PyObject *py_get_current_context(PyObject *self, PyObject *Py_UNUSED(args)) {
    GLFWwindow *handle = glfwGetCurrentContext();
    if (handle == NULL) Py_RETURN_NONE;
    PyGLFWWindow *window = (PyGLFWWindow *)glfwGetWindowUserPointer(handle);
    if (window == NULL) Py_RETURN_NONE;
    Py_INCREF(window);
    return (PyObject *)window;
}

static PyObject *py_swap_buffers(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwSwapBuffers(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_poll_events(PyObject *self, PyObject *Py_UNUSED(args)) {
    glfwPollEvents();
    Py_RETURN_NONE;
}

static PyObject *py_wait_events(PyObject *self, PyObject *Py_UNUSED(args)) {
    glfwWaitEvents();
    Py_RETURN_NONE;
}

static PyObject *py_wait_events_timeout(PyObject *self, PyObject *arg) {
    double timeout = PyFloat_AsDouble(arg);
    if (PyErr_Occurred()) return NULL;
    glfwWaitEventsTimeout(timeout);
    Py_RETURN_NONE;
}

static PyObject *py_post_empty_event(PyObject *self, PyObject *Py_UNUSED(args)) {
    glfwPostEmptyEvent();
    Py_RETURN_NONE;
}

static PyObject *py_window_should_close(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    return PyBool_FromLong(glfwWindowShouldClose(window->window));
}

static PyObject *py_set_window_should_close(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int value;
    if (!PyArg_ParseTuple(args, "Op", &window_obj, &value)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    glfwSetWindowShouldClose(window->window, value);
    Py_RETURN_NONE;
}

static PyObject *py_get_window_size(PyObject *self, PyObject *arg) {
    int width, height;
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwGetWindowSize(window->window, &width, &height);
    return Py_BuildValue("(ii)", width, height);
}

static PyObject *py_set_window_size(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int width, height;
    if (!PyArg_ParseTuple(args, "Oii", &window_obj, &width, &height)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    glfwSetWindowSize(window->window, width, height);
    Py_RETURN_NONE;
}

static PyObject *py_get_framebuffer_size(PyObject *self, PyObject *arg) {
    int width, height;
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwGetFramebufferSize(window->window, &width, &height);
    return Py_BuildValue("(ii)", width, height);
}

static PyObject *py_get_window_attrib(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int attrib;
    if (!PyArg_ParseTuple(args, "Oi", &window_obj, &attrib)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    return PyLong_FromLong(glfwGetWindowAttrib(window->window, attrib));
}

static PyObject *py_get_cursor_pos(PyObject *self, PyObject *arg) {
    double x, y;
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwGetCursorPos(window->window, &x, &y);
    return Py_BuildValue("(dd)", x, y);
}

static PyObject *py_get_mouse_button(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int button;
    if (!PyArg_ParseTuple(args, "Oi", &window_obj, &button)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    return PyLong_FromLong(glfwGetMouseButton(window->window, button));
}

static PyObject *py_get_key(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int key;
    if (!PyArg_ParseTuple(args, "Oi", &window_obj, &key)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    return PyLong_FromLong(glfwGetKey(window->window, key));
}

static PyObject *py_get_time(PyObject *self, PyObject *Py_UNUSED(args)) {
    return PyFloat_FromDouble(glfwGetTime());
}

static PyObject *py_set_time(PyObject *self, PyObject *arg) {
    double value = PyFloat_AsDouble(arg);
    if (PyErr_Occurred()) return NULL;
    glfwSetTime(value);
    Py_RETURN_NONE;
}

static PyObject *py_get_clipboard_string(PyObject *self, PyObject *args) {
    PyObject *window_obj = Py_None;
    if (!PyArg_ParseTuple(args, "|O", &window_obj)) return NULL;
    GLFWwindow *window = optional_window_pointer(window_obj);
    if (window == NULL && PyErr_Occurred()) return NULL;
    const char *text = glfwGetClipboardString(window);
    if (text == NULL) Py_RETURN_NONE;
    return PyUnicode_FromString(text);
}

static PyObject *py_set_clipboard_string(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    const char *text;
    if (!PyArg_ParseTuple(args, "Os", &window_obj, &text)) return NULL;
    GLFWwindow *window = optional_window_pointer(window_obj);
    if (window == NULL && PyErr_Occurred()) return NULL;
    glfwSetClipboardString(window, text);
    Py_RETURN_NONE;
}

static PyObject *py_set_window_title(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    const char *title;
    if (!PyArg_ParseTuple(args, "Os", &window_obj, &title)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    glfwSetWindowTitle(window->window, title);
    Py_RETURN_NONE;
}

static PyObject *py_show_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwShowWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_hide_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwHideWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_iconify_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwIconifyWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_restore_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwRestoreWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_maximize_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwMaximizeWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_focus_window(PyObject *self, PyObject *arg) {
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwFocusWindow(window->window);
    Py_RETURN_NONE;
}

static PyObject *py_swap_interval(PyObject *self, PyObject *arg) {
    int interval = (int)PyLong_AsLong(arg);
    if (PyErr_Occurred()) return NULL;
    glfwSwapInterval(interval);
    Py_RETURN_NONE;
}

static PyObject *py_set_input_mode(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int mode, value;
    if (!PyArg_ParseTuple(args, "Oii", &window_obj, &mode, &value)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    glfwSetInputMode(window->window, mode, value);
    Py_RETURN_NONE;
}

static PyObject *py_get_input_mode(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int mode;
    if (!PyArg_ParseTuple(args, "Oi", &window_obj, &mode)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    return PyLong_FromLong(glfwGetInputMode(window->window, mode));
}

static PyObject *py_get_window_pos(PyObject *self, PyObject *arg) {
    int x, y;
    PyGLFWWindow *window = window_from_object(arg);
    if (window == NULL) return NULL;
    glfwGetWindowPos(window->window, &x, &y);
    return Py_BuildValue("(ii)", x, y);
}

static PyObject *py_set_window_pos(PyObject *self, PyObject *args) {
    PyObject *window_obj;
    int x, y;
    if (!PyArg_ParseTuple(args, "Oii", &window_obj, &x, &y)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    glfwSetWindowPos(window->window, x, y);
    Py_RETURN_NONE;
}

static PyObject *set_window_callback(PyObject *args, PyObject **slot, void (*setter)(GLFWwindow *, void *), void *trampoline) {
    PyObject *window_obj;
    PyObject *callback;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "callback must be callable or None");
        return NULL;
    }
    Py_INCREF(callback);
    Py_XDECREF(*slot);
    *slot = callback;
    setter(window->window, callback == Py_None ? NULL : trampoline);
    Py_RETURN_NONE;
}

static void set_key_callback_c(GLFWwindow *window, void *callback) { glfwSetKeyCallback(window, (GLFWkeyfun)callback); }
static void set_cursor_pos_callback_c(GLFWwindow *window, void *callback) { glfwSetCursorPosCallback(window, (GLFWcursorposfun)callback); }
static void set_window_size_callback_c(GLFWwindow *window, void *callback) { glfwSetWindowSizeCallback(window, (GLFWwindowsizefun)callback); }
static void set_char_callback_c(GLFWwindow *window, void *callback) { glfwSetCharCallback(window, (GLFWcharfun)callback); }
static void set_scroll_callback_c(GLFWwindow *window, void *callback) { glfwSetScrollCallback(window, (GLFWscrollfun)callback); }
static void set_mouse_button_callback_c(GLFWwindow *window, void *callback) { glfwSetMouseButtonCallback(window, (GLFWmousebuttonfun)callback); }
static void set_window_close_callback_c(GLFWwindow *window, void *callback) { glfwSetWindowCloseCallback(window, (GLFWwindowclosefun)callback); }

static PyObject *py_set_key_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->key_callback, set_key_callback_c, trampoline_key);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_cursor_pos_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->cursor_pos_callback, set_cursor_pos_callback_c, trampoline_cursor_pos);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_window_size_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->window_size_callback, set_window_size_callback_c, trampoline_window_size);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_char_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->char_callback, set_char_callback_c, trampoline_char);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_scroll_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->scroll_callback, set_scroll_callback_c, trampoline_scroll);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_mouse_button_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->mouse_button_callback, set_mouse_button_callback_c, trampoline_mouse_button);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_window_close_callback(PyObject *self, PyObject *args) {
    PyObject *window_obj = NULL;
    PyObject *callback = NULL;
    if (!PyArg_ParseTuple(args, "OO", &window_obj, &callback)) return NULL;
    PyGLFWWindow *window = window_from_object(window_obj);
    if (window == NULL) return NULL;
    PyObject *tuple = Py_BuildValue("OO", window_obj, callback);
    PyObject *result = set_window_callback(tuple, &window->window_close_callback, set_window_close_callback_c, trampoline_window_close);
    Py_DECREF(tuple);
    return result;
}

static PyObject *py_set_error_callback(PyObject *self, PyObject *callback) {
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "callback must be callable or None");
        return NULL;
    }
    Py_INCREF(callback);
    Py_XDECREF(error_callback);
    error_callback = callback;
    glfwSetErrorCallback(callback == Py_None ? NULL : trampoline_error);
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"init", py_init, METH_NOARGS, NULL},
    {"terminate", py_terminate, METH_NOARGS, NULL},
    {"window_hint", py_window_hint, METH_VARARGS, NULL},
    {"default_window_hints", py_default_window_hints, METH_NOARGS, NULL},
    {"create_window", py_create_window, METH_VARARGS, NULL},
    {"destroy_window", py_destroy_window, METH_O, NULL},
    {"make_context_current", py_make_context_current, METH_O, NULL},
    {"get_current_context", py_get_current_context, METH_NOARGS, NULL},
    {"swap_buffers", py_swap_buffers, METH_O, NULL},
    {"poll_events", py_poll_events, METH_NOARGS, NULL},
    {"wait_events", py_wait_events, METH_NOARGS, NULL},
    {"wait_events_timeout", py_wait_events_timeout, METH_O, NULL},
    {"post_empty_event", py_post_empty_event, METH_NOARGS, NULL},
    {"window_should_close", py_window_should_close, METH_O, NULL},
    {"set_window_should_close", py_set_window_should_close, METH_VARARGS, NULL},
    {"get_window_size", py_get_window_size, METH_O, NULL},
    {"set_window_size", py_set_window_size, METH_VARARGS, NULL},
    {"get_framebuffer_size", py_get_framebuffer_size, METH_O, NULL},
    {"get_window_attrib", py_get_window_attrib, METH_VARARGS, NULL},
    {"get_cursor_pos", py_get_cursor_pos, METH_O, NULL},
    {"get_mouse_button", py_get_mouse_button, METH_VARARGS, NULL},
    {"get_key", py_get_key, METH_VARARGS, NULL},
    {"get_time", py_get_time, METH_NOARGS, NULL},
    {"set_time", py_set_time, METH_O, NULL},
    {"get_clipboard_string", py_get_clipboard_string, METH_VARARGS, NULL},
    {"set_clipboard_string", py_set_clipboard_string, METH_VARARGS, NULL},
    {"set_window_title", py_set_window_title, METH_VARARGS, NULL},
    {"show_window", py_show_window, METH_O, NULL},
    {"hide_window", py_hide_window, METH_O, NULL},
    {"iconify_window", py_iconify_window, METH_O, NULL},
    {"restore_window", py_restore_window, METH_O, NULL},
    {"maximize_window", py_maximize_window, METH_O, NULL},
    {"focus_window", py_focus_window, METH_O, NULL},
    {"swap_interval", py_swap_interval, METH_O, NULL},
    {"set_input_mode", py_set_input_mode, METH_VARARGS, NULL},
    {"get_input_mode", py_get_input_mode, METH_VARARGS, NULL},
    {"get_window_pos", py_get_window_pos, METH_O, NULL},
    {"set_window_pos", py_set_window_pos, METH_VARARGS, NULL},
    {"set_key_callback", py_set_key_callback, METH_VARARGS, NULL},
    {"set_cursor_pos_callback", py_set_cursor_pos_callback, METH_VARARGS, NULL},
    {"set_window_size_callback", py_set_window_size_callback, METH_VARARGS, NULL},
    {"set_char_callback", py_set_char_callback, METH_VARARGS, NULL},
    {"set_scroll_callback", py_set_scroll_callback, METH_VARARGS, NULL},
    {"set_mouse_button_callback", py_set_mouse_button_callback, METH_VARARGS, NULL},
    {"set_window_close_callback", py_set_window_close_callback, METH_VARARGS, NULL},
    {"set_error_callback", py_set_error_callback, METH_O, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "glfw._glfw",
    "StaticPython GLFW bindings backed by a statically linked GLFW library.",
    -1,
    methods
};

PyMODINIT_FUNC PyInit__glfw(void) {
    PyGLFWWindow_Type.tp_name = "glfw.Window";
    PyGLFWWindow_Type.tp_basicsize = sizeof(PyGLFWWindow);
    PyGLFWWindow_Type.tp_dealloc = (destructor)PyGLFWWindow_dealloc;
    PyGLFWWindow_Type.tp_repr = (reprfunc)PyGLFWWindow_repr;
    PyGLFWWindow_Type.tp_flags = Py_TPFLAGS_DEFAULT;
    if (PyType_Ready(&PyGLFWWindow_Type) < 0) {
        return NULL;
    }
    PyObject *module = PyModule_Create(&moduledef);
    if (module == NULL) {
        return NULL;
    }
    Py_INCREF(&PyGLFWWindow_Type);
    if (PyModule_AddObject(module, "Window", (PyObject *)&PyGLFWWindow_Type) < 0) {
        Py_DECREF(&PyGLFWWindow_Type);
        Py_DECREF(module);
        return NULL;
    }
    return module;
}
"""


def _parse_glfw_constants(header: Path) -> dict[str, int]:
    constants: dict[str, int] = {}
    define_re = re.compile(r"^\s*#\s*define\s+GLFW_([A-Za-z0-9_]+)\s+(.+?)\s*(?:/\*.*)?$")
    for line in header.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = define_re.match(line)
        if not match:
            continue
        name, raw_value = match.groups()
        if "(" in name:
            continue
        value_text = raw_value.split("//", 1)[0].split("/*", 1)[0].strip()
        if not value_text:
            continue
        if value_text.startswith("GLFW_"):
            alias = value_text.removeprefix("GLFW_")
            if alias in constants:
                constants[name] = constants[alias]
            continue
        if not re.fullmatch(r"-?(?:0x[0-9A-Fa-f]+|\d+)", value_text):
            continue
        constants[name] = int(value_text, 0)
    return constants


def _render_glfw_python_module(constants: dict[str, int]) -> str:
    lines = [
        '"""StaticPython GLFW bindings backed by a statically linked GLFW library."""',
        "",
        "from ._glfw import *  # noqa: F401,F403",
        "",
        f"__version__ = {GLFW_VERSION!r}",
        "",
    ]
    for name, value in sorted(constants.items()):
        lines.append(f"{name} = {value!r}")
    lines.extend(
        [
            "",
            "def get_version():",
            "    return VERSION_MAJOR, VERSION_MINOR, VERSION_REVISION",
            "",
            "def get_version_string():",
            "    return __version__",
            "",
            "__all__ = [name for name in globals() if not name.startswith('_')]",
            "",
        ]
    )
    return "\n".join(lines)


def _render_glfw_c_module(constants: dict[str, int]) -> str:
    lines = [
        '"""Compatibility module exposing GLFW_* names like pyGLFW."""',
        "",
        "from . import *  # noqa: F401,F403",
        "",
    ]
    for name in sorted(constants):
        lines.append(f"GLFW_{name} = {name}")
    lines.extend(
        [
            "",
            "__all__ = [name for name in globals() if name.startswith('GLFW_')]",
            "",
        ]
    )
    return "\n".join(lines)


def prepare_glfw_project(context) -> None:
    source_root = glfw_source_root(context)
    header = source_root / "include" / "GLFW" / "glfw3.h"
    if not header.exists():
        raise RuntimeError(f"GLFW header is missing: {header}")
    constants = _parse_glfw_constants(header)
    if "KEY_A" not in constants or "VISIBLE" not in constants:
        raise RuntimeError("GLFW constants could not be parsed from glfw3.h")
    write_source_text(context, "Lib/glfw/__init__.py", _render_glfw_python_module(constants))
    write_source_text(context, "Lib/glfw/GLFW.py", _render_glfw_c_module(constants))
    write_source_text(context, "glfw_builtin/staticpython_glfw.c", GLFW_EXTENSION_SOURCE)
    write_source_text(context, "PCbuild/glfw._glfw.vcxproj", _render_glfw_project())


def _copy_built_glfw_library(context, build_dir: Path) -> None:
    candidates = sorted(
        build_dir.rglob(GLFW_STATIC_LIBRARY),
        key=lambda path: (0 if "Release" in path.parts else 1, len(path.parts), str(path)),
    )
    if not candidates:
        raise RuntimeError(f"GLFW build did not produce {GLFW_STATIC_LIBRARY}")
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], output_dir / GLFW_STATIC_LIBRARY)


def prepare_glfw_artifacts(context) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    if (output_dir / GLFW_STATIC_LIBRARY).exists():
        context.log(f"using existing GLFW static library at {output_dir.relative_to(context.source_root)}")
        return

    ensure_tool("cmake")
    source_dir = glfw_source_root(context)
    build_dir = glfw_build_dir(context)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    run(
        context.log,
        [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            "-G",
            "Visual Studio 17 2022",
            "-A",
            "x64",
            "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_C_FLAGS:STRING=/MT",
            "-DCMAKE_C_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DGLFW_BUILD_DOCS=OFF",
            "-DGLFW_BUILD_EXAMPLES=OFF",
            "-DGLFW_BUILD_TESTS=OFF",
            "-DGLFW_INSTALL=OFF",
            "-DGLFW_LIBRARY_TYPE=STATIC",
        ],
        cwd=source_dir,
        timeout=60 * 15,
    )
    run(
        context.log,
        [
            "cmake",
            "--build",
            str(build_dir),
            "--config",
            "Release",
            "--",
            "/m:1",
            "/p:CL_MPCount=1",
            "/p:UseMultiToolTask=false",
        ],
        cwd=build_dir,
        timeout=60 * 30,
    )
    _copy_built_glfw_library(context, build_dir)


LIBRARY_INTEGRATION = github_library(
    name="glfw",
    repo="glfw/glfw",
    ref=GLFW_VERSION,
    ref_kind="tags",
    license_expression="Zlib",
    source_mapping={
        "CMakeLists.txt": f"glfw_builtin/glfw-{GLFW_VERSION}/CMakeLists.txt",
        "cmake": f"glfw_builtin/glfw-{GLFW_VERSION}/cmake",
        "deps": f"glfw_builtin/glfw-{GLFW_VERSION}/deps",
        "include": f"glfw_builtin/glfw-{GLFW_VERSION}/include",
        "src": f"glfw_builtin/glfw-{GLFW_VERSION}/src",
    },
    source_ignore_patterns=[
        ".git",
        ".github",
        "docs",
        "examples",
        "tests",
    ],
    materialized_paths=[
        "Lib/glfw/__init__.py",
        "Lib/glfw/GLFW.py",
        "glfw_builtin/staticpython_glfw.c",
        f"glfw_builtin/glfw-{GLFW_VERSION}/include/GLFW/glfw3.h",
        "PCbuild/glfw._glfw.vcxproj",
    ],
    cleanup_paths=[
        f"glfw_builtin/glfw-{GLFW_VERSION}",
    ],
    python_packages=["glfw"],
    static_library_projects_release_x64=[
        "glfw._glfw.vcxproj",
    ],
    native_static_projects=[
        {
            "project": "glfw._glfw.vcxproj",
            "guid": GLFW_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "glfw._glfw",
            "pyinit": "PyInit__glfw",
        }
    ],
    python_link_dependencies_release_x64=[
        "glfw._glfw.lib",
        GLFW_STATIC_LIBRARY,
        *GLFW_SYSTEM_LIBRARIES,
    ],
    overlay_entries=[
        "imgui_glfw_runtime_test.py",
    ],
    prepare_source_hooks=[prepare_glfw_project],
    pre_build_hooks=[prepare_glfw_artifacts],
)
