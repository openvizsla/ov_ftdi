from collections import namedtuple

SDRAMParams = namedtuple("SDRAMParams", 
    ('databits', # Width of the SDRAM bus in bits
     'rowbits', 
     'colbits', 
     'bankbits', 
     'burst', 
     'tRESET', 
     'tCL',
     'tRP', 
     'tRFC', 
     'tRCD', 
     'tREFI', 
     'tWR'
    ))

SDRAMModelParams = namedtuple("SDRAMModelParams", ('modelname', 'filename', 'params'))

_models = {
    'mt48lc16m16a2': SDRAMModelParams(
        'mt48lc16m16a2',
        '3rdparty/mt48lc16m16a2.v',
        SDRAMParams(
            databits=16, rowbits=13, colbits=9, bankbits=2,
            burst=512, tRESET=200, tCL=3, tRP=4, tRFC=12, tRCD=4,
            tREFI=780, tWR=2)
    )
}

def getModelNames():
    return _models.keys()

def getSDRAMModelParams(named, chips_wide=1):
    mname, fname, chip_params = _models[named]

    pd = chip_params._asdict()
    pd.update({'databits': chip_params.databits * chips_wide})
    return SDRAMModelParams(mname, fname, SDRAMParams(**pd))


def getSDRAMParams(named, chips_wide=1):
    return getSDRAMModelParams(named, chips_wide).params


# Basic sanity unit tests; make sure none of these assert
import unittest
class BasicSDPUnitTests(unittest.TestCase):
    def testGetModels(self):
        self.assertGreaterEqual(len(getModelNames()), 1)

    def testGetSDRAMModelParams(self):
        # Just check that it doesn't assert
        m = next(iter(getModelNames()))
        s = getSDRAMModelParams(m, 1)
        s = getSDRAMModelParams(m, 2)
        s = getSDRAMParams(m, 2)

    # Ensure databit calculation is correct
    def testSDRAMArray(self):
        s = getSDRAMModelParams("mt48lc16m16a2", 2)
        self.assertEquals(s.params.databits, 32)


