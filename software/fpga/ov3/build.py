from ovplatform.ov3 import Platform
from ovhw.top import OV3

def gen_mapfile(ov3_mod):
    # Generate mapfile for tool / sw usage
    r = ""
    for name, csrs, mapaddr, rmap in sorted(
            ov3_mod.csrbankarray.banks, key=lambda x: x[2]):
        r += "\n# "+name+"\n"
        reg_base = 0x200 * mapaddr
        r += name.upper()+"_BASE = "+hex(reg_base)+"\n"

        for n, csr in enumerate(csrs):
            nr = (csr.size + 7)//8
            if nr == 1:
                r += "%s = %#x\n" % ((name + "_" + csr.name).upper(), reg_base)
            else:
                r += "%s = %#x:%#x\n" % ((name + "_" + csr.name).upper(), reg_base, reg_base + nr - 1)
            reg_base += nr

    return r

if __name__ == "__main__":
    import sys

    plat = Platform()
    top = OV3(plat)

    _, build_dir, build_name = sys.argv

    open("{}/map.txt".format(build_dir), "w").write(gen_mapfile(top))

    plat.build(top, build_dir=build_dir, build_name=build_name)
