def gather_files(top_module):
    """
    Traverse a tree of modules and gather any 'extra_files' attributes. Useful
    for Modules that wrap an "Instance"; where the "Instance" wraps a
    non-builtin
    """

    files = []
    l = [(None, top_module)]
    while l:
        (_, mod), l = l[0], l[1:]

        l.extend(mod._submodules)

        if hasattr(mod, "extra_files"):
            files.extend(mod.extra_files)
    return files

def par(*args):
    """
    Run multiple iterators in parallel, returning a tuple of the collected
    outputs
    """

    al = list(args)
    outputs = [None] * len(args)
    count = len(args)
    while count:
        for n, a in enumerate(al):
            if a:
                try:
                    next(a)
                except StopIteration as si:
                    al[n] = None
                    outputs[n] = si.value
                    count -= 1
        if count:
            yield
    return tuple(outputs)

def run(arg):
    """
    Repeatedly advance a single iterator until it returns a value.
    Primarily useful in testing nested generators.
    """
    try:
        while 1: next(arg)
    except StopIteration as si:
        return si.value


