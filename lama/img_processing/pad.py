#!/usr/bin/env python


import os
from os.path import splitext, basename, join
import sys
from typing import List

import SimpleITK as sitk
import yaml
import numpy as np
from logzero import logger as logging
from addict import Dict

from lama import common
from lama.utilities.extract_region_from_sices import write_roi_from_image_stack


def pad_volumes(volpaths: List, max_dims: List, outdir: str, filetype: str='nrrd'):
    """
    Pad volumes, masks, labels. Output files will have same name as original, but be in a new output folder

    Parameters
    ----------
    volpaths
        paths to volumes
    max_dims
        dimensions to pad to (z, y, x)
    outdir
        path to output dir
    """
    logging.info('Padding to {} - {} volumes/masks:'.format(str(max_dims), str(len(volpaths))))
    pad_info = Dict()

    for path in volpaths:

        loader = common.LoadImage(path)
        vol = loader.img
        if not vol:
            logging.error('error loading image for padding: {}'.format(loader.error_msg))
            sys.exit()
        vol_dims = vol.GetSize()

        # The voxel differences between the vol dims and the max dims
        diffs = [m - v for m, v in zip(max_dims, vol_dims)]

        # How many pixels to add to the upper bounds of each dimension, divide by two and round down to nearest int
        upper_extend = [d // 2 for d in diffs]

        # In case of differnces that cannot be /2. Get the remainder to add to the lower bound
        remainders = [d % 2 for d in diffs]

        # Add the remainders to the upper bound extension to get the lower bound extension
        lower_extend = [u + r for u, r in zip(upper_extend, remainders)]

        # if any values are negative, stop. We need all volumes to be the same size
        for ex_val in zip(lower_extend, upper_extend):

            if ex_val[0] < 0 or ex_val[1] < 0:
                msg = ("\ncan't pad images\n"
                       "{} is larger than the specified volume size\n"
                       "Current vol size:{},\n"
                       "Max vol size: {}"
                       "\nCheck the 'pad_dims' in the config file\n".format(basename(path), str(vol_dims),
                                                                            str(max_dims)))

                logging.error(msg)
                raise common.LamaDataException(msg)

        # Pad the volume. New pixels set to zero
        padded_vol = sitk.ConstantPad(vol, upper_extend, lower_extend, 0)
        padded_vol.SetOrigin((0, 0, 0))
        padded_vol.SetSpacing((1, 1, 1))

        input_basename = splitext(basename(path))[0]
        padded_outname = join(outdir, '{}.{}'.format(input_basename, filetype))
        sitk.WriteImage(padded_vol, padded_outname, True)
        pad_info['data'][input_basename]['pad'] = [upper_extend, lower_extend]
    return pad_info


def unpad_roi(pad_info, inverted_labels, voxel_size, outdir):
    """
    Given a dir with inverted rois in VTK format, return a list of ROIs that have been corrected for the padding that
    occured just before registration
    Parameters
    ----------
    pad_info: str
        path to pad_info file
        formated like 'volume id no extension, upper padding amounts, lower padding amounts
        eg:
            20160406_ATP1A2_E14.5_2.3g_WT_ND_scaled_4.7297_pixel_13.9999,[44, 31, 70],[44, 31, 70]
            20150305_HHIPL1_E14.5_19.1h_WT_XY_REC_scaled_4.6878_pixel_14.0,[31, 5, 40],[32, 5, 40]
    inverted_labels: str
        path to dir containing inverted labels

    Returns
    -------
    """

    if __name__ == '__main__':
        logpath = join(outdir, 'Extract_roi.log')
        common.init_logging(logpath)

    #Load the pad_info. This was generated by LAMA while padding before the registration started
    pad_info_dict = {}
    with open(pad_info, 'r') as pf:
        config = yaml.load(pf)
        full_res_root_dir = config['root_folder']
        full_res_subfolder_name = config['full_res_subfolder']
        log_file_pattern = config.get('log_file_endswith')
        voxel_size_entry = config['voxel_size_log_entry']
        data = config['data']

    # Extract the amount of padding for each volume
    for vol_id, vol_info in data.items():
        pad = vol_info['pad']
        pad_info_dict[vol_id] = pad

    unpadded_results = {}
    dirs = os.listdir(inverted_labels)
    for dir_ in dirs:
        folder = join(inverted_labels, dir_)
        if os.path.isdir(folder):
            label_file = join(folder, [x for x in os.listdir(folder) if x.endswith('.nrrd')][0])
            roi_starts, roi_ends = extract_roi_from_label(label_file)
            start_pad, end_pad = pad_info_dict[basename(folder)]

            unpadded_roi_start = np.array(roi_starts) - np.array(start_pad)
            unpadded_roi_end = np.array(roi_ends) - np.array(start_pad)
            unpadded_results[basename(folder)] = (unpadded_roi_start, unpadded_roi_end)

    # Now scale back up to size of full res images
    for vol_id, vol_info in data.items():
        full_res_name = vol_info['full_res_folder']
        full_res_folder = join(full_res_root_dir, full_res_name, full_res_subfolder_name)
        try:
            log = [join(full_res_folder, x) for x in os.listdir(full_res_folder) if x.endswith(log_file_pattern)][0]
        except OSError:
            print(vol_id, 'is changed on the server')
            continue
        except IndexError:
            print("can't find log file for", vol_id)
            continue
        with open(log, 'r') as lf:
            original_voxel_size = None
            for line in lf:
                if line.startswith(voxel_size_entry):
                    original_voxel_size = float(line.split('=')[1].strip())
                    print(original_voxel_size)
                    break
        if not original_voxel_size:
            print("Could not acquire voxel size for", vol_id)
            continue

        scaling_factor = voxel_size // original_voxel_size
        roi_starts, roi_ends = unpadded_results[vol_id]
        new_starts = np.array(roi_starts) * scaling_factor
        new_ends = np.array(roi_ends) * scaling_factor
        roi_out_path = join(outdir, vol_id + 'roi.nrrd')
        write_roi_from_image_stack(full_res_folder, roi_out_path, new_starts, new_ends)


def extract_roi_from_label(label_file):

    img = sitk.ReadImage(label_file)
    binary_img = sitk.BinaryThreshold(img, 0, 0, 0, 1)
    conn = sitk.RelabelComponent(sitk.ConnectedComponent(binary_img))
    ls = sitk.LabelStatisticsImageFilter()
    ls.Execute(img, conn)
    bbox = ls.GetBoundingBox(1)  # x,x,y,y, z,z
    roi_starts = (bbox[0], bbox[2], bbox[4])
    roi_ends =  (bbox[1], bbox[3], bbox[5])
    return roi_starts, roi_ends

if __name__ == '__main__':

    import argparse

    # if sys.argv[1] == 'pad':

    parser = argparse.ArgumentParser("pad a folder of images")
    parser.add_argument('-i', '--indir', dest='indir', help='directory with images', required=True)
    parser.add_argument('-o', '--out_dir', dest='outdir', help='where to put padded images', required=True)
    parser.add_argument('-d', '--new_dims', dest='new_dims', nargs=3, type=int, help='xyz to pad to (with spaces)',
                        required=True)
    args, _ = parser.parse_known_args()

    input_imgs = common.get_file_paths(args.indir)
    pad_volumes(input_imgs, args.new_dims, args.outdir)

    # elif sys.argv[1] == 'unpad_roi':
    #     parser = argparse.ArgumentParser("unpad a folder of ROIs in vtk format")
    #     parser.add_argument('-i', '--pad_info', dest='pad_info', help='', required=True)
    #     parser.add_argument('-l', '--inverted_labels', dest='labels', help='inverted labels', required=True)
    #     parser.add_argument('-v', '--voxel_size', dest='voxel_size', help='voxel size of the scaled images',
    #                         required=True, type=float)
    #     parser.add_argument('-o', '--outdir', dest='out_dir', help='', required=True)
    #
    #     args, _ = parser.parse_known_args()
    #     unpadded_rois = unpad_roi(args.pad_info, args.labels, args.voxel_size, args.out_dir)
        # for name, rois in unpadded_rois.iteritems():
        #     print name, rois[0], rois[1]