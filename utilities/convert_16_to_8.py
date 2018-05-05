#!/usr/bin/env python

import SimpleITK as sitk
import os
from os.path import abspath
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import common


def convert_16_bit_to_8bit(indir, outdir):

    clobber = True if outdir == 'clobber' else False

    paths = common.get_file_paths(abspath(indir))

    for inpath in paths:
        img = sitk.ReadImage(inpath)
        arr = sitk.GetArrayFromImage(img)

        if arr.dtype not in (np.uint16, np.int16):
            print("skipping {}. Not 16bit".format(inpath))
            continue

        if arr.max() <= 255:
            print("16bit image but with 8 bit intensity range {} leave as it is".format(inpath))
            continue

        # Fix the negative values, which can be caused by  the registration process. therwise we end up with hihglights
        # where there should be black

        if arr.dtype == np.int16:
            # transform to unsigned range
            print('unsigned short')
            negative_range = np.power(2, 16) / 2
            arr += negative_range
        # Do the cast
        arr2 = arr/256
        arr_cast = arr2.astype(np.uint8)
        print arr_cast.min(), arr_cast.max()

        out_img = sitk.GetImageFromArray(arr_cast)
        basename = os.path.basename(inpath)
        if clobber:
            outpath = inpath
        else:
            outpath = os.path.join(abspath(outdir), basename)
        sitk.WriteImage(out_img, outpath, True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser("Rescale 16 bit images to 8bit")
    parser.add_argument('-i', dest='indir', help='dir with vols to convert', required=True)
    parser.add_argument('-o', dest='outdir', help='dir to put vols in', required=True)
    args = parser.parse_args()
    convert_16_bit_to_8bit(args.indir, args.outdir)