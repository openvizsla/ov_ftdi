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


class TIProxy:
    """
    Transaction Initiator proxy; for sequencing CSR writes from a separate
    generator
    """
    def __init__(self):
        self.tl = []
        self.done = False

    def issue(self, arg):
        self.tl.append(arg)

    def wait(self):
        while self.tl:
            yield

    def fini(self):
        self.done = True

    def _ini_iterator(self):
        while 1:
            if self.done:
                raise StopIteration()

            if self.tl:
                yield self.tl[0]
                self.tl = self.tl[1:]
            else:
                yield

