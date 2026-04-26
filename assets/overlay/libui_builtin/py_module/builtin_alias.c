#include <Python.h>

PyMODINIT_FUNC PyInit_core(void);

PyMODINIT_FUNC
PyInit__libui_core(void)
{
    return PyInit_core();
}
