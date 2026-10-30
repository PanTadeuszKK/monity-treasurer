import unittest
from ui import window_geometry


class GeometryTests(unittest.TestCase):
    def test_windows_fit_and_center_at_resolutions_and_scaling(self):
        for screen in [(1024,768),(1366,768),(1920,1080),(2560,1440)]:
            for scale in [1,1.25,1.5,2]:
                with self.subTest(screen=screen,scale=scale):
                    width,height,x,y=window_geometry(*screen,1000,900,scale)
                    self.assertGreaterEqual(x,0)
                    self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+round(width*scale),screen[0])
                    self.assertLessEqual(y+round(height*scale)+40,screen[1])

    def test_child_center_matches_parent_unless_screen_edge_clamps(self):
        width,height,x,y=window_geometry(1920,1080,500,400,1,(200,100,1000,700))
        self.assertEqual((x,y),(450,250))
        width,height,x,y=window_geometry(1366,768,800,600,1,(1200,650,1000,700))
        self.assertLessEqual(x+width,1366)
        self.assertLessEqual(y+height,768)
