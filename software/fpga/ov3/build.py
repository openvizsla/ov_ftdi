from ovplatform.ov3 import Platform
from ovhw.top import OV3

if __name__ == "__main__":
    plat = Platform()
    plat.build_cmdline(OV3(plat))
