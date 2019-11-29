from ovplatform.ov3 import Platform
from ovhw.top import OV3
import sys
import argparse
import os
import json
import zipfile
import shutil


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('-d', '--build-dir', default='build', help='Override build directory.')
    p.add_argument('-n', '--build-name', default='ov3', help='Override build name.')
    p.add_argument('-p', '--generate-fwpkg', action='store_true', default=False, help='Generate firmware package after build finishes.')
    p.add_argument('-m', '--mibuild-params', default='{}', type=json.loads, help='Extra mibuild parameters (in JSON).')
    return p.parse_args()


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
    args = parse_args()

    mibuild_params = {
        'build_dir': args.build_dir,
        'build_name': args.build_name,
    }

    if len(args.mibuild_params) != 0:
        mibuild_params.update(args.mibuild_params)

    os.makedirs(args.build_dir, exist_ok=True)

    plat = Platform()
    top = OV3(plat)

    # Paths
    bit_file_name = args.build_name + '.bit'
    map_file_path = os.path.join(args.build_dir, "map.txt")
    bit_file_path = os.path.join(args.build_dir, bit_file_name)
    fwpkg_file_path = os.path.join(args.build_dir, args.build_name + '.fwpkg')

    # Build the register map
    open(map_file_path, "w").write(gen_mapfile(top))

    # Run the FPGA toolchain to build the bit file
    plat.build(top, **mibuild_params)

    # Generate fwpkg
    if args.generate_fwpkg and os.path.isfile(bit_file_path):
        with zipfile.ZipFile(fwpkg_file_path, 'w', compression=zipfile.ZIP_DEFLATED) as pack:
            with pack.open('map.txt', 'w') as dst, open(map_file_path, 'rb') as src:
                shutil.copyfileobj(src, dst)
            with pack.open(bit_file_name, 'w') as dst, open(bit_file_path, 'rb') as src:
                shutil.copyfileobj(src, dst)
