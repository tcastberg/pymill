import unittest
import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir) 

import mill as Mill

class MillTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv, find_dotenv
        load_dotenv(find_dotenv())
        cls.key = os.getenv('MILLHEAT_KEY')
        cls.token = os.getenv('MILLHEAT_TOKEN')
        cls.user = os.getenv('MILLHEAT_USER')
        cls.passwd = os.getenv('MILLHEAT_PASS')
        cls.mill = Mill.Mill(cls.key, cls.token, cls.user, cls.passwd)

    def test_1_connect(cls):
        cls.mill.sync_connect()

    def test_2_discover_rooms(cls):
        cls.mill.sync_update_rooms()

    def test_3_discover_devices(cls):
        cls.mill.sync_update_heaters()

    # def test_7_discover_independent(cls):
    #     for home in cls.mill.homes:
    #         cls.assertTrue(cls.mill.devices_independent(home), True)
            
if __name__ == '__main__':
    mill = unittest.TestLoader().loadTestsFromTestCase(MillTests)
    unittest.TextTestRunner(verbosity=3).run(mill)
