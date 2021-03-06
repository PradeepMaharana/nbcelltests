# *****************************************************************************
#
# Copyright (c) 2019, the nbcelltests authors.
#
# This file is part of the nbcelltests library, distributed under the terms of
# the Apache License 2.0.  The full license can be found in the LICENSE file.
#
import nbformat
import os
import sys
import subprocess
from nbconvert import ScriptExporter
from tempfile import NamedTemporaryFile
from .shared import extract_extrametadata
from .define import LintMessage, LintType


def lint_lines_per_cell(cell_lines, max_lines_per_cell=-1):
    ret = []
    if max_lines_per_cell < 0:
        return [], True
    for i, lines_in_cell in enumerate(cell_lines):
        ret.append(
            LintMessage(
                i + 1,  # TODO: ambiguous - e.g. cell 0 or first cell?
                'Checking lines in cell (max={max_}; actual={actual})'.format(
                    max_=max_lines_per_cell,
                    actual=lines_in_cell),
                LintType.LINES_PER_CELL,
                lines_in_cell <= max_lines_per_cell))
    return ret, all([x.passed for x in ret])


def lint_cells_per_notebook(cell_count, max_cells_per_notebook=-1):
    if max_cells_per_notebook < 0:
        return [], True
    passed = cell_count <= max_cells_per_notebook
    return [LintMessage(-1, 'Checking cells per notebook (max={max_}; actual={actual})'.format(max_=max_cells_per_notebook, actual=cell_count), LintType.CELLS_PER_NOTEBOOK, passed)], passed


def lint_function_definitions(functions, max_function_definitions=-1):
    if max_function_definitions < 0:
        return [], True
    passed = functions <= max_function_definitions
    return [LintMessage(-1, 'Checking functions per notebook (max={max_}; actual={actual})'.format(max_=max_function_definitions, actual=functions), LintType.FUNCTION_DEFINITIONS, passed)], passed


def lint_class_definitions(classes, max_class_definitions=-1):
    if max_class_definitions < 0:
        return [], True
    passed = classes <= max_class_definitions
    return [LintMessage(-1, 'Checking classes per notebook (max={max_}; actual={actual})'.format(max_=max_class_definitions, actual=classes), LintType.CLASS_DEFINITIONS, passed)], passed


def lint_kernelspec(kernelspec, kernelspec_requirements=False):
    """Check that kernelspec fulfills kernelspec_requirements.

    If kernelspec_requirements is False, no check will happen.

    If kernelspec_requirements is None, requires an empty kernelspec
    (use to enforce saving without kernelspec details).

    Otherwise, kernelspec must contain at least the same key: value
    pairs as are in kernelspec_requirements.
    """
    if kernelspec_requirements is False:
        return [], True
    # assumes kernelspec dict values are hashable (they're strings)
    passed = set(kernelspec.items()).issuperset(kernelspec_requirements.items())
    return [LintMessage(-1, 'Checking kernelspec (min. required={required}; actual={actual})'.format(required=kernelspec_requirements, actual=kernelspec), LintType.KERNELSPEC, passed)], passed


def lint_magics(magics, whitelist=None, blacklist=None):
    """Check that magics are acceptable.

    Specify either a whitelist or a blacklist (or neither), but not
    both.
    """
    if whitelist is None and blacklist is None:
        return [], True

    if whitelist is not None and blacklist is not None:
        raise ValueError("Must specify either a whitelist or a blacklist, not both. Blacklist: {}; whitelist: {}".format(blacklist, whitelist))

    if whitelist is not None:
        bad = set(magics) - set(whitelist)
        msg = "missing from whitelist:"
    elif blacklist is not None:
        bad = set(magics) & set(blacklist)
        msg = "present in blacklist:"

    passed = not(bad)
    return [LintMessage(-1, 'Checking magics{}'.format(" ({} {})".format(msg, bad) if bad else ""), LintType.MAGICS, passed)], passed


def run(notebook, executable=None, rules=None, noqa_regex=None):
    nb = nbformat.read(notebook, 4)
    extra_metadata = extract_extrametadata(nb, noqa_regex=noqa_regex)
    ret = []
    passed = True

    rules = rules or {}
    extra_metadata.update(rules)

    # TODO: consider warning if referring to non-existent rules
    rules_to_remove = extra_metadata['noqa'] & extra_metadata.keys()
    for rule in rules_to_remove:
        del extra_metadata[rule]

    # TODO: lintfail is more like lintpassed?

    if 'lines_per_cell' in extra_metadata:
        lintret, lintfail = lint_lines_per_cell(extra_metadata['cell_lines'], max_lines_per_cell=extra_metadata['lines_per_cell'])
        ret.extend(lintret)
        passed = passed and lintfail

    if 'cells_per_notebook' in extra_metadata:
        lintret, lintfail = lint_cells_per_notebook(extra_metadata['cell_count'], max_cells_per_notebook=extra_metadata['cells_per_notebook'])
        ret.extend(lintret)
        passed = passed and lintfail

    if 'function_definitions' in extra_metadata:
        lintret, lintfail = lint_function_definitions(extra_metadata['functions'], max_function_definitions=extra_metadata['function_definitions'])
        ret.extend(lintret)
        passed = passed and lintfail

    if 'class_definitions' in extra_metadata:
        lintret, lintfail = lint_class_definitions(extra_metadata['classes'], max_class_definitions=extra_metadata['class_definitions'])
        ret.extend(lintret)
        passed = passed and lintfail

    if 'kernelspec_requirements' in extra_metadata:
        lintret, lintfail = lint_kernelspec(kernelspec=extra_metadata['kernelspec'], kernelspec_requirements=extra_metadata['kernelspec_requirements'])
        ret.extend(lintret)
        passed = passed and lintfail

    if 'magics_whitelist' in extra_metadata or 'magics_blacklist' in extra_metadata:
        lintret, lintfail = lint_magics(magics=extra_metadata['magics'], whitelist=extra_metadata.get('magics_whitelist', None), blacklist=extra_metadata.get('magics_blacklist', None))
        ret.extend(lintret)
        passed = passed and lintfail

    if executable:
        exp = ScriptExporter()
        (body, resources) = exp.from_notebook_node(nb)
        tf = NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf8')
        tf_name = tf.name
        try:
            tf.write(body)
            tf.close()
            executable.append(tf_name)
            ret2 = _run_and_capture_utf8(executable)
            msg = ret2.stdout + '\t' + ret2.stderr
            ret.append(LintMessage(-1, 'Checking lint:\n' + msg.strip(), LintType.LINTER, False if msg.strip() else True))
        finally:
            os.remove(tf_name)

    return ret, passed


def _run_and_capture_utf8(args):
    # PYTHONIOENCODING for pyflakes on Windows
    run_kw = {'env': dict(os.environ, PYTHONIOENCODING='utf8')} if sys.platform == 'win32' else {}
    return subprocess.run(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', **run_kw)


def runWithHTMLReturn(notebook, executable=None, rules=None):
    ret = ''
    ret_tmp, fail = run(notebook, executable=executable, rules=rules)
    for lint in ret_tmp:
        lint = lint.to_html()
        ret += '<p>' + lint + '</p>'
    return '<div style="display: flex; flex-direction: column;">' + ret + '</div>', fail


if __name__ == '__main__':
    # TODO: doesn't support the typical interface of run (e.g. rules)
    if len(sys.argv) != 2:
        raise Exception('Usage:python -m nbcelltests.lint <ipynb file>')
    notebook = sys.argv[1]
    ret, passed = run(notebook, ['flake8', '--ignore=W391'])
    if passed:
        print('\n'.join(str(r) for r in ret))
        sys.exit(0)
    else:
        print('\n'.join(str(r) for r in ret))
        sys.exit(1)
