/* Copyright 2026 xqy2006. SPDX-License-Identifier: Apache-2.0 */
#include "Python.h"
#include "staticpython_pack.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STATICPYTHON_STRINGIFY_INNER(value) #value
#define STATICPYTHON_STRINGIFY(value) STATICPYTHON_STRINGIFY_INNER(value)
#define STATICPYTHON_CPYTHON_ABI \
    "cp" STATICPYTHON_STRINGIFY(PY_MAJOR_VERSION) STATICPYTHON_STRINGIFY(PY_MINOR_VERSION)

static const StaticPythonPackV1 *const *staticpython_packs = NULL;
static size_t staticpython_pack_count = 0;
static struct _frozen *staticpython_frozen_modules = NULL;
static struct _inittab *staticpython_builtin_modules = NULL;
static char staticpython_last_error[512] = "";
static int staticpython_registered = 0;

static int
staticpython_fail(const char *message)
{
    (void)snprintf(
        staticpython_last_error,
        sizeof(staticpython_last_error),
        "%s",
        message != NULL ? message : "unknown StaticPython runtime error"
    );
    return -1;
}

static int
staticpython_fail_pack(const StaticPythonPackV1 *pack, const char *message)
{
    (void)snprintf(
        staticpython_last_error,
        sizeof(staticpython_last_error),
        "pack %s: %s",
        pack != NULL && pack->name != NULL ? pack->name : "<unnamed>",
        message
    );
    return -1;
}

const char *
StaticPython_LastError(void)
{
    return staticpython_last_error;
}

const char *
StaticPython_RuntimeABI(void)
{
    return "staticpython-pack-v1-" STATICPYTHON_CPYTHON_ABI;
}

static const StaticPythonResourceV1 *
staticpython_find_resource(const char *path, Py_ssize_t path_length)
{
    for (size_t pack_index = 0; pack_index < staticpython_pack_count; pack_index++) {
        const StaticPythonPackV1 *pack = staticpython_packs[pack_index];
        for (size_t index = 0; index < pack->resource_count; index++) {
            const StaticPythonResourceV1 *resource = &pack->resources[index];
            if (resource->path != NULL
                && (Py_ssize_t)strlen(resource->path) == path_length
                && memcmp(resource->path, path, (size_t)path_length) == 0) {
                return resource;
            }
        }
    }
    return NULL;
}

static int
staticpython_resource_is_directory(const char *path, Py_ssize_t path_length)
{
    for (size_t pack_index = 0; pack_index < staticpython_pack_count; pack_index++) {
        const StaticPythonPackV1 *pack = staticpython_packs[pack_index];
        for (size_t index = 0; index < pack->resource_count; index++) {
            const char *candidate = pack->resources[index].path;
            if (candidate == NULL || (Py_ssize_t)strlen(candidate) <= path_length) {
                continue;
            }
            if (path_length == 0) {
                return 1;
            }
            if (memcmp(candidate, path, (size_t)path_length) == 0
                && candidate[path_length] == '/') {
                return 1;
            }
        }
    }
    return 0;
}

static int
staticpython_unicode_key(PyObject *arg, const char **key, Py_ssize_t *key_length)
{
    *key = PyUnicode_AsUTF8AndSize(arg, key_length);
    return *key != NULL;
}

static PyObject *
staticpython_resource_file_info(PyObject *self, PyObject *arg)
{
    const char *key;
    Py_ssize_t key_length;
    (void)self;
    if (!staticpython_unicode_key(arg, &key, &key_length)) {
        return NULL;
    }
    const StaticPythonResourceV1 *resource = staticpython_find_resource(key, key_length);
    if (resource == NULL) {
        Py_RETURN_NONE;
    }
    return Py_BuildValue(
        "ssn",
        resource->module_name != NULL ? resource->module_name : "",
        resource->blob_id != NULL ? resource->blob_id : "",
        (Py_ssize_t)resource->size
    );
}

static PyObject *
staticpython_resource_read(PyObject *self, PyObject *arg)
{
    const char *key;
    Py_ssize_t key_length;
    (void)self;
    if (!staticpython_unicode_key(arg, &key, &key_length)) {
        return NULL;
    }
    const StaticPythonResourceV1 *resource = staticpython_find_resource(key, key_length);
    if (resource == NULL || resource->data == NULL) {
        Py_RETURN_NONE;
    }
    PyObject *payload = PyBytes_FromStringAndSize(
        (const char *)resource->data,
        (Py_ssize_t)resource->data_size
    );
    if (payload == NULL) {
        return NULL;
    }
    PyObject *result = Py_BuildValue("Ni", payload, (int)resource->compression);
    return result;
}

static PyObject *
staticpython_resource_kind(PyObject *self, PyObject *arg)
{
    const char *key;
    Py_ssize_t key_length;
    (void)self;
    if (!staticpython_unicode_key(arg, &key, &key_length)) {
        return NULL;
    }
    if (staticpython_find_resource(key, key_length) != NULL) {
        return PyLong_FromLong(1);
    }
    return PyLong_FromLong(staticpython_resource_is_directory(key, key_length) ? 2 : 0);
}

static int
staticpython_tuple_contains_utf8(PyObject *tuple, const char *value, Py_ssize_t value_length)
{
    Py_ssize_t count = PyTuple_GET_SIZE(tuple);
    for (Py_ssize_t index = 0; index < count; index++) {
        PyObject *item = PyTuple_GET_ITEM(tuple, index);
        Py_ssize_t item_length;
        const char *item_text = PyUnicode_AsUTF8AndSize(item, &item_length);
        if (item_text == NULL) {
            return -1;
        }
        if (item_length == value_length
            && memcmp(item_text, value, (size_t)value_length) == 0) {
            return 1;
        }
    }
    return 0;
}

static PyObject *
staticpython_resource_children(PyObject *self, PyObject *arg)
{
    const char *key;
    Py_ssize_t key_length;
    (void)self;
    if (!staticpython_unicode_key(arg, &key, &key_length)) {
        return NULL;
    }
    if (!staticpython_resource_is_directory(key, key_length)) {
        Py_RETURN_NONE;
    }

    PyObject *children = PyTuple_New(0);
    if (children == NULL) {
        return NULL;
    }
    for (size_t pack_index = 0; pack_index < staticpython_pack_count; pack_index++) {
        const StaticPythonPackV1 *pack = staticpython_packs[pack_index];
        for (size_t index = 0; index < pack->resource_count; index++) {
            const char *candidate = pack->resources[index].path;
            if (candidate == NULL) {
                continue;
            }
            const char *child = candidate;
            if (key_length > 0) {
                if (strncmp(candidate, key, (size_t)key_length) != 0
                    || candidate[key_length] != '/') {
                    continue;
                }
                child = candidate + key_length + 1;
            }
            const char *slash = strchr(child, '/');
            Py_ssize_t child_length = slash != NULL
                ? (Py_ssize_t)(slash - child)
                : (Py_ssize_t)strlen(child);
            if (child_length == 0) {
                continue;
            }
            int contains = staticpython_tuple_contains_utf8(children, child, child_length);
            if (contains < 0) {
                Py_DECREF(children);
                return NULL;
            }
            if (contains) {
                continue;
            }
            PyObject *name = PyUnicode_FromStringAndSize(child, child_length);
            if (name == NULL) {
                Py_DECREF(children);
                return NULL;
            }
            Py_ssize_t old_count = PyTuple_GET_SIZE(children);
            PyObject *expanded = PyTuple_New(old_count + 1);
            if (expanded == NULL) {
                Py_DECREF(name);
                Py_DECREF(children);
                return NULL;
            }
            for (Py_ssize_t offset = 0; offset < old_count; offset++) {
                PyObject *existing = PyTuple_GET_ITEM(children, offset);
                Py_INCREF(existing);
                PyTuple_SET_ITEM(expanded, offset, existing);
            }
            PyTuple_SET_ITEM(expanded, old_count, name);
            Py_DECREF(children);
            children = expanded;
        }
    }
    return children;
}

static PyMethodDef staticpython_resource_methods[] = {
    {"file_info", staticpython_resource_file_info, METH_O, NULL},
    {"read", staticpython_resource_read, METH_O, NULL},
    {"children", staticpython_resource_children, METH_O, NULL},
    {"kind", staticpython_resource_kind, METH_O, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef staticpython_resource_module = {
    PyModuleDef_HEAD_INIT,
    "_staticpython_resource_store",
    NULL,
    0,
    staticpython_resource_methods,
    NULL,
    NULL,
    NULL,
    NULL,
};

PyMODINIT_FUNC
PyInit__staticpython_resource_store(void)
{
    return PyModule_Create(&staticpython_resource_module);
}

static int
staticpython_validate_pack(const StaticPythonPackV1 *pack)
{
    if (pack == NULL) {
        return staticpython_fail("pack pointer is NULL");
    }
    if (pack->struct_size < sizeof(StaticPythonPackV1)) {
        return staticpython_fail_pack(pack, "descriptor is smaller than StaticPythonPackV1");
    }
    if (pack->abi_version != STATICPYTHON_PACK_ABI_VERSION) {
        return staticpython_fail_pack(pack, "unsupported StaticPython pack ABI version");
    }
    if (pack->name == NULL || pack->name[0] == '\0') {
        return staticpython_fail_pack(pack, "name is required");
    }
    if (pack->cpython_abi == NULL
        || strcmp(pack->cpython_abi, STATICPYTHON_CPYTHON_ABI) != 0) {
        return staticpython_fail_pack(pack, "CPython minor ABI does not match the runtime");
    }
    if (pack->frozen_module_count != 0 && pack->frozen_modules == NULL) {
        return staticpython_fail_pack(pack, "frozen module table is NULL");
    }
    if (pack->builtin_module_count != 0 && pack->builtin_modules == NULL) {
        return staticpython_fail_pack(pack, "builtin module table is NULL");
    }
    if (pack->resource_count != 0 && pack->resources == NULL) {
        return staticpython_fail_pack(pack, "resource table is NULL");
    }
    return 0;
}

static int
staticpython_validate_duplicates(
    const StaticPythonPackV1 *const *packs,
    size_t pack_count
)
{
    for (size_t left_pack = 0; left_pack < pack_count; left_pack++) {
        const StaticPythonPackV1 *left = packs[left_pack];
        for (size_t left_index = 0; left_index < left->frozen_module_count; left_index++) {
            const char *name = left->frozen_modules[left_index].name;
            if (name == NULL) {
                return staticpython_fail_pack(left, "frozen module name is NULL");
            }
            for (size_t right_pack = left_pack; right_pack < pack_count; right_pack++) {
                const StaticPythonPackV1 *right = packs[right_pack];
                size_t start = right_pack == left_pack ? left_index + 1 : 0;
                for (size_t right_index = start; right_index < right->frozen_module_count; right_index++) {
                    if (strcmp(name, right->frozen_modules[right_index].name) == 0) {
                        return staticpython_fail_pack(right, "duplicate frozen module name");
                    }
                }
            }
        }
        for (size_t left_index = 0; left_index < left->resource_count; left_index++) {
            const char *path = left->resources[left_index].path;
            if (path == NULL) {
                return staticpython_fail_pack(left, "resource path is NULL");
            }
            for (size_t right_pack = left_pack; right_pack < pack_count; right_pack++) {
                const StaticPythonPackV1 *right = packs[right_pack];
                size_t start = right_pack == left_pack ? left_index + 1 : 0;
                for (size_t right_index = start; right_index < right->resource_count; right_index++) {
                    if (strcmp(path, right->resources[right_index].path) == 0) {
                        return staticpython_fail_pack(right, "duplicate virtual resource path");
                    }
                }
            }
        }
    }
    return 0;
}

int
StaticPython_RegisterPacks(
    const StaticPythonPackV1 *const *packs,
    size_t pack_count
)
{
    size_t frozen_count = 0;
    size_t builtin_count = 1; /* resource provider */
    size_t base_frozen_count = 0;

    staticpython_last_error[0] = '\0';
    if (staticpython_registered) {
        return staticpython_fail("packs may only be registered once");
    }
    if (Py_IsInitialized()) {
        return staticpython_fail("packs must be registered before Python initialization");
    }
    if (pack_count != 0 && packs == NULL) {
        return staticpython_fail("pack array is NULL");
    }
    for (size_t index = 0; index < pack_count; index++) {
        if (staticpython_validate_pack(packs[index]) < 0) {
            return -1;
        }
        frozen_count += packs[index]->frozen_module_count;
        builtin_count += packs[index]->builtin_module_count;
    }
    if (staticpython_validate_duplicates(packs, pack_count) < 0) {
        return -1;
    }

    if (PyImport_FrozenModules != NULL) {
        while (PyImport_FrozenModules[base_frozen_count].name != NULL) {
            base_frozen_count++;
        }
    }
    frozen_count += base_frozen_count;
    staticpython_frozen_modules = (struct _frozen *)calloc(
        frozen_count + 1,
        sizeof(struct _frozen)
    );
    staticpython_builtin_modules = (struct _inittab *)calloc(
        builtin_count + 1,
        sizeof(struct _inittab)
    );
    if (staticpython_frozen_modules == NULL || staticpython_builtin_modules == NULL) {
        free(staticpython_frozen_modules);
        free(staticpython_builtin_modules);
        staticpython_frozen_modules = NULL;
        staticpython_builtin_modules = NULL;
        return staticpython_fail("out of memory while merging pack tables");
    }

    for (size_t index = 0; index < base_frozen_count; index++) {
        staticpython_frozen_modules[index] = PyImport_FrozenModules[index];
    }
    size_t frozen_offset = base_frozen_count;
    size_t builtin_offset = 0;
    staticpython_builtin_modules[builtin_offset].name = "_staticpython_resource_store";
    staticpython_builtin_modules[builtin_offset].initfunc = PyInit__staticpython_resource_store;
    builtin_offset++;

    for (size_t pack_index = 0; pack_index < pack_count; pack_index++) {
        const StaticPythonPackV1 *pack = packs[pack_index];
        for (size_t index = 0; index < pack->frozen_module_count; index++) {
            const StaticPythonFrozenModuleV1 *source = &pack->frozen_modules[index];
            struct _frozen *target = &staticpython_frozen_modules[frozen_offset++];
            target->name = source->name;
            target->code = source->code;
            target->size = source->size;
            target->is_package = source->is_package;
#if PY_VERSION_HEX < 0x030D0000
            target->get_code = source->get_code;
#endif
        }
        for (size_t index = 0; index < pack->builtin_module_count; index++) {
            staticpython_builtin_modules[builtin_offset].name = pack->builtin_modules[index].name;
            staticpython_builtin_modules[builtin_offset].initfunc = pack->builtin_modules[index].initfunc;
            builtin_offset++;
        }
    }

    if (PyImport_ExtendInittab(staticpython_builtin_modules) != 0) {
        free(staticpython_frozen_modules);
        free(staticpython_builtin_modules);
        staticpython_frozen_modules = NULL;
        staticpython_builtin_modules = NULL;
        return staticpython_fail("PyImport_ExtendInittab failed");
    }
    PyImport_FrozenModules = staticpython_frozen_modules;
    staticpython_packs = packs;
    staticpython_pack_count = pack_count;

    for (size_t index = 0; index < pack_count; index++) {
        if (packs[index]->before_initialize != NULL
            && packs[index]->before_initialize() != 0) {
            return staticpython_fail_pack(packs[index], "before_initialize hook failed");
        }
    }
    staticpython_registered = 1;
    return 0;
}
