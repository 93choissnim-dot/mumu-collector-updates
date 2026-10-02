"""Menu/page recognition across capture color and backdrop changes."""
import unittest
import cv2
import numpy as np
from vision import Vision,foreground_luma_check
from validate_overlays import composite
from task_catalog import PAGE_MARKERS

class MenuColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()

    def menu(self):return composite(self.v,'menu_farm','menu_wood','menu_mine','sleep_menu')

    def test_bright_capture_menu_matches_without_absolute_color(self):
        for shift in (35,45):
            im=np.clip(self.menu().astype(np.float32)+shift,0,255).astype(np.uint8)
            for width in (640,960,1280):
                s=self.v.recognize(cv2.resize(im,(width,width*9//16)))
                self.assertEqual(s.state,'menu',(shift,width,s.state))
                self.assertTrue(any(d.get('accepted') and d.get('color_method') in {'structure','foreground_luma'} for d in s.diagnostics.values()))

    def test_unrelated_background_pixels_do_not_affect_foreground_comparison(self):
        rng=np.random.default_rng(754)
        for name in ('menu_farm','menu_wood','menu_mine'):
            c,_=self.v.templates[name];mask=self.v.foreground_masks[name]
            protected=cv2.dilate(mask.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
            patch=c.copy();patch[~protected]=rng.integers(0,255,(int((~protected).sum()),3),dtype=np.uint8)
            passed,_=foreground_luma_check(patch,c,mask)
            self.assertTrue(passed,name)

    def test_missing_one_icon_is_not_menu_even_when_other_two_are_bright(self):
        for missing in ('farm','wood','mine'):
            im=composite(self.v,*(('menu_'+r) for r in ('farm','wood','mine') if r!=missing))
            im=np.clip(im.astype(np.float32)+40,0,255).astype(np.uint8)
            self.assertNotEqual(self.v.recognize(im).state,'menu')

    def test_dimmed_menu_and_flat_foregrounds_are_rejected(self):
        dark=(self.menu().astype(np.float32)*.5).astype(np.uint8)
        self.assertNotEqual(self.v.recognize(dark).state,'menu')
        for name in ('menu_farm','menu_wood','menu_mine'):
            c,_=self.v.templates[name];mask=self.v.foreground_masks[name]
            patch=np.full_like(c,220)
            passed,_=foreground_luma_check(patch,c,mask)
            self.assertFalse(passed,name)

    def test_flat_icon_and_random_noise_never_count_as_menu(self):
        rng=np.random.default_rng(755)
        for mode in ('flat','noise'):
            im=self.menu()
            for name in ('menu_farm','menu_wood','menu_mine'):
                x1,y1,x2,y2=self.v.specs[name]['box']
                im[y1:y2,x1:x2]=(190,210,230) if mode=='flat' else rng.integers(0,255,(y2-y1,x2-x1,3),dtype=np.uint8)
            self.assertNotEqual(self.v.recognize(im).state,'menu')

    def test_modal_covering_two_icons_does_not_expose_menu(self):
        im=np.clip(self.menu().astype(np.float32)+40,0,255).astype(np.uint8)
        im[50:480,250:870]=(190,200,210)
        self.assertNotEqual(self.v.recognize(im).state,'menu')

    def test_each_extra_page_accepts_verified_capture_cast(self):
        for page,markers in PAGE_MARKERS.items():
            im=composite(self.v,*markers)
            shifted=np.clip(im.astype(np.float32)*1.18,0,255).astype(np.uint8)
            self.assertEqual(self.v.recognize(shifted).state,page,page)
            for missing in markers:
                im=composite(self.v,*(m for m in markers if m!=missing))
                shifted=np.clip(im.astype(np.float32)*1.18,0,255).astype(np.uint8)
                recognized=self.v.recognize(shifted)
                if page=='boss_mode':
                    # Partial chooser blocks its background but cannot enter.
                    self.assertNotIn('x_boss_mode_normal',recognized.matches,missing)
                else:self.assertNotEqual(recognized.state,page,(page,missing))

    def test_boss_claim_stays_distinct_from_empty_with_capture_cast(self):
        for state in ('active','empty'):
            name='x_boss_'+state
            other='x_boss_'+('empty' if state=='active' else 'active')
            im=composite(self.v,*PAGE_MARKERS['boss_rank'],name)
            for light in (.9,1,1.18,1.25):
                cast=np.clip(im.astype(np.float32)*light,0,255).astype(np.uint8)
                for width in (640,960,1280):
                    s=self.v.recognize(cv2.resize(cast,(width,width*9//16)))
                    self.assertEqual(s.state,'boss_rank')
                    self.assertIn(name,s.matches,(state,light,width))
                    self.assertNotIn(other,s.matches,(state,light,width))

    def test_dim_or_missing_boss_button_is_not_activated(self):
        for fill in ('dim','flat','absent'):
            im=composite(self.v,*PAGE_MARKERS['boss_rank'],'x_boss_active')
            x1,y1,x2,y2=self.v.specs['x_boss_active']['box']
            if fill=='dim':im[y1:y2,x1:x2]=(im[y1:y2,x1:x2]*.5).astype(np.uint8)
            else:im[y1:y2,x1:x2]=100 if fill=='flat' else 0
            self.assertNotIn('x_boss_active',self.v.recognize(im).matches,fill)

if __name__=='__main__':unittest.main()
