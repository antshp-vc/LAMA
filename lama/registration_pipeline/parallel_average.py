"""
020620

A go at making populaiton average construction parallelizable across the grid.

Take a root directory with inputs. Poll this directory to get a list of specimens.
Look in the output directory and see what folders are avaialbe to see if there are remaiing specimens to process for a
stage.

If one job runner finds a stage complete, but there's not completion file, create an exlusive file and then go about
starting the next stage and.

"""

from pathlib import Path
from os.path import join
import time
from lama.registration_pipeline.validate_config import LamaConfig
from lama.registration_pipeline.run_lama import generate_elx_parameters, ELX_PARAM_PREFIX
from lama import common
from lama.elastix.elastix_registration import TargetBasedRegistration
from logzero import logger as logging
import SimpleITK as sitk


def make_avg(root_dir: Path,  out_path: Path):

    paths = []
    for spec_dir in root_dir.iterdir():
        if not spec_dir.is_dir():
            continue
        paths.append(spec_dir / f'{spec_dir.name}.nrrd')

    avg = common.average(paths)
    logging.info(f'\nCreating average from:')
    logging.info('\n'.join([str(x) for x in paths]))
    sitk.WriteImage(avg, str(out_path))


def check_stage_done(root_dir) -> bool:
    for spec_dir in root_dir.iterdir():
        if not spec_dir.is_dir():
            continue
        if not (spec_dir / 'spec_done').is_file():
            return False
    return True


def run_elastix_stage(inputs_dir: Path, config_path: Path, out_dir: Path) -> Path:
    """
    Run the registrations specified in the config file

    Returns
    -------
    The path to the final registrered images
    """

    config = LamaConfig(config_path)

    avg_dir = out_dir / 'averages'
    avg_dir.mkdir(exist_ok=True)

    elastix_stage_parameters = generate_elx_parameters(config, do_pairwise=config['pairwise_registration'])

    # Set the fixed volume up for the first stage. This will checnge each stage if doing population average
    fixed_vol = config['fixed_volume']

    # Get list of specimens
    spec_ids = [Path(x).stem for x in common.get_file_paths(inputs_dir)]

    for i, reg_stage in enumerate(config['registration_stage_params']):

        stage_id = reg_stage['stage_id']
        logging.info(stage_id)
        stage_dir = Path(config.stage_dirs[stage_id])

        # Make stage dir if not made by another instance of the script
        stage_dir.mkdir(exist_ok=True, parents=True)

        starting_avg = stage_dir / 'avg_started'
        average_done = stage_dir / "avg_done"

        while True:  # Pick up unstarted speciemens. Only break when reg and avergae complete

            # Check if any specimens left (It's possible the avg is being made but all specimens are registered)
            spec_stage_dirs = [x.name for x in stage_dir.iterdir() if x.is_dir()]
            not_started = set(spec_ids).difference(spec_stage_dirs)

            if len(not_started) > 0:  # Some specimens left
                next_spec_id = list(not_started)[0]
            else:  # All specimens are being processed

                while True:
                    if not check_stage_done(stage_dir):
                        time.sleep(5)
                    else:
                        break # Stage registraitons finished

                if average_done.is_file():
                    break # Next stage

                if starting_avg.is_file():
                    time.sleep(5) # wait for average to finish
                else:
                    try:
                        open(starting_avg, 'x')
                    except FileExistsError:
                        pass
                    else:
                        average_path = avg_dir / f'{stage_id}.nrrd'
                        make_avg(stage_dir, average_path)
                        open(average_done, 'x').close()
                        break
                time.sleep(5)

            # Get the input for this specimen
            if i == 0:  # The first stage
                moving = inputs_dir / f'{next_spec_id}.nrrd'
            else:
                # moving = previous_stage / next_spec_id / 'output' / 'registrations'
                moving = list(config.stage_dirs.values())[i-1] / next_spec_id / f'{next_spec_id}.nrrd'
                fixed_vol = avg_dir / f'{list(config.stage_dirs.keys())[i-1]}.nrrd'
            reg_method = TargetBasedRegistration

            # Make the elastix parameter file for this stage
            elxparam = elastix_stage_parameters[stage_id]
            elxparam_path = stage_dir / f'{ELX_PARAM_PREFIX}{stage_id}.txt'

            if not elxparam_path.is_file():
                with open(elxparam_path, 'w') as fh:
                    if elxparam:
                        fh.write(elxparam)

            fixed_mask = None

            logging.info(moving)
            # Do the registrations
            registrator = reg_method(elxparam_path,
                                     moving,
                                     stage_dir,
                                     config['filetype'],
                                     config['threads'],
                                     fixed_mask
                                     )

            registrator.set_target(fixed_vol)

            registrator.run()  # Do the registrations for a single stage
            spec_done = stage_dir / next_spec_id / 'spec_done'  # The directory gets created in .run()
            open(spec_done, 'x').close()


if __name__ == '__main__':
    import sys
    inputs_dir_ = Path(sys.argv[1])
    config_path_ = Path(sys.argv[2])
    output_dir_ = Path(sys.argv[3])

run_elastix_stage(inputs_dir_, config_path_, output_dir_)