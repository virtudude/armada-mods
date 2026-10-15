"""Synthetic font tests; installed-game validation is opt-in and never a fixture."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import fonts
from assets import AssetError


class FontTests(unittest.TestCase):
    @staticmethod
    def table_map(data):
        count = struct.unpack_from('>H', data, 4)[0]
        return {tag.decode(): (offset, data[offset:offset+length], check)
                for tag, check, offset, length in
                (struct.unpack_from('>4sIII', data, 12+16*i) for i in range(count))}

    @staticmethod
    def synthetic():
        return dict(name='Synthetic Test', bold=False, italic=False,
            contours=[[], [[(0,0,1),(100,500,0),(200,0,1)]]], codes=[32,65],
            advances=[220,300], ascent=600, descent=-100, leading=50,
            kerning=[(65,65,-20)])

    def test_ttf_tables_checksums_unicode_and_metrics(self):
        data = fonts.build_ttf(self.synthetic())
        self.assertEqual(fonts.checksum(data), 0xb1b0afba)
        tables = self.table_map(data)
        self.assertEqual(set(tables), {'OS/2','head','hhea','hmtx','maxp','loca','glyf','name','post','cmap','kern'})
        for tag, (offset, table, check) in tables.items():
            self.assertEqual(offset % 4, 0)
            if tag == 'head':
                table = table[:8] + bytes(4) + table[12:]
            self.assertEqual(fonts.checksum(table), check, tag)
        self.assertEqual(struct.unpack_from('>H', tables['maxp'][1], 4)[0], 3)
        self.assertEqual(struct.unpack_from('>Hh', tables['hmtx'][1], 8), (300,0))
        cmap = tables['cmap'][1][12:]
        count = struct.unpack_from('>H',cmap,6)[0]//2
        self.assertEqual(count,3)
        ends = struct.unpack_from('>'+str(count)+'H',cmap,14)
        starts = struct.unpack_from('>'+str(count)+'H',cmap,16+2*count)
        deltas = struct.unpack_from('>'+str(count)+'H',cmap,16+4*count)
        self.assertEqual(ends, (32,65,65535))
        self.assertEqual(starts, ends)
        self.assertEqual([(a+b)&65535 for a,b in zip(starts,deltas)], [1,2,0])
        self.assertEqual(struct.unpack_from('>HHh',tables['kern'][1],18),(2,2,-20))

    def test_quadratic_glyph_retains_control_point(self):
        data,box = fonts._glyph(self.synthetic()['contours'][1])
        self.assertEqual(box,(0,0,200,500))
        self.assertEqual(struct.unpack_from('>h',data)[0],1)
        self.assertEqual(struct.unpack_from('>H',data,10)[0],2)
        self.assertEqual(data[14:17], bytes([1,0,1]))
        self.assertEqual(struct.unpack_from('>3h',data,17),(0,100,100))
        self.assertEqual(struct.unpack_from('>3h',data,23),(0,500,-500))

    def test_font3_truncation_and_unsupported_swf(self):
        for data in (b'',b'not a font',b'FWS\x09\xff\xff\xff\xff'):
            with self.assertRaises(AssetError):
                fonts.extract_fonts(data)
        with self.assertRaises(AssetError):
            fonts.parse_font3(b'\x01\0\x80\0\x01x\x01\0')

    def test_missing_game_returns_clear_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            result=fonts.prepare_fonts(directory,directory)
            self.assertEqual(result['fonts'],{})
            self.assertIn('Could not convert',result['warnings'][0])

    @unittest.skipUnless(os.environ.get('FALLOUT4_TEST_GAME'), 'Set FALLOUT4_TEST_GAME for installed font verification')
    def test_installed_fonts_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            result=fonts.prepare_fonts(os.environ['FALLOUT4_TEST_GAME'],directory)
            self.assertEqual(result['warnings'],[])
            self.assertEqual(set(result['fonts']),{'main','bold','terminal','controller'})
            self.assertEqual(result['fonts']['main']['name'],'Roboto Condensed')
            self.assertGreater(result['fonts']['main']['glyphs'],700)
            for font in result['fonts'].values():
                self.assertEqual(fonts.checksum((Path(directory)/font['path']).read_bytes()),0xb1b0afba)
            self.assertEqual(fonts.prepare_fonts(os.environ['FALLOUT4_TEST_GAME'],directory),result)
            (Path(directory)/result['fonts']['main']['path']).unlink()
            self.assertEqual(fonts.prepare_fonts(os.environ['FALLOUT4_TEST_GAME'],directory),result)
            self.assertTrue((Path(directory)/result['fonts']['main']['path']).is_file())


if __name__ == '__main__':
    unittest.main()
