"""
The entry point to running permutation-based statistics.


Usage
-----

cli:
    ~$ python3.6 run_permutation_stats.py
       -w test_data/registration_test_data/baseline
       -m test_data/registration_test_data/mutant
       -o test_data/stats_test_data/test_output
       -n 1000

as a module:
    run_permutation_stats.run(test_data/registration_test_data/baseline,
                            data/registration_test_data/mutant,
                            test_data/stats_test_data/test_output,
                            1000)


Currently, this module works only with organ volume data. The voxel-based methods are currently too big to do this.
Think about including voxel-based stats in the future

Outline of pipeline
-------------------
Before running the permutation statistics we need to have run jobrunner.py on the baseline and mutant data.

The main function in this module run() calles the following functions during the pipeline:

get_organ_volume_data and get_staging_data
    search the registration output folders for the CSVs that contain the organ volumes
    and staging data and collate into single csvs.


distributions.null and distributions.alternative
    Use the dataframes from the precedding functions to generate null and alternative p-value distributiuon dataframes

p_thresholds.get_thresholds
    Using the null and alternative distributions, these functions generate organ-spceific p-value thresholds.
    These are generated for both line-level and specimen level calls.

annotate
    This function creates final results CSVs.
        Puts a line-level csv in the line/output/stats_/
        Puts specimen-level csv files in line/output/stats_/specimen_level

"""

import numpy as np
from lama import common
import pandas as pd
from pathlib import Path
from datetime import date
from logzero import logger as logging

from lama.stats.permutation_stats import distributions
from lama.stats.permutation_stats import p_thresholds
from lama.paths import specimen_iterator


GENOTYPE_P_COL_NAME = 'genotype_effect_p_value'
PERM_SIGNIFICANT_COL_NAME = 'significant_cal_p'


def get_organ_volume_data(root_dir: Path) -> pd.DataFrame:
    """
    Given a root registration directory, collate all the organ volume CSVs into one file.
    Write out the combined organ volume CSV into the root registration directory.

    Parameters
    ----------
    root_dir
        The path to the root registration directory

    Returns
    -------
    The combined dataframe of all the organ volumes
    """
    output_dir = root_dir / 'output'

    dataframes = []

    for line_dir, specimen_dir in specimen_iterator(output_dir):

        organ_vol_file = specimen_dir / 'output' / common.ORGAN_VOLUME_CSV_FILE

        if not organ_vol_file.is_file():
            raise FileNotFoundError(f'Cannot find organ volume file {organ_vol_file}')

        df = pd.read_csv(organ_vol_file, index_col=0)
        # TODO: Is this needed?
        # df['line'] = line_dir.name
        dataframes.append(df)

    # Write the concatenated organ vol file to single csv
    all_organs = pd.concat(dataframes)

    outpath = output_dir / common.ORGAN_VOLUME_CSV_FILE
    all_organs.to_csv(outpath)

    return all_organs


def get_staging_data(root_dir: Path) -> pd.DataFrame:
    """
    Given a root registration dorectory, collate all the staging CSVs into one file.
    Write out the combined organ volume CSV into the root registration directory.

    Parameters
    ----------
    root_dir
        The path to the root registration directory

    Returns
    -------
    The combined dataframe of all the organ volumes
    """
    output_dir = root_dir / 'output'

    dataframes = []

    for line_dir, specimen_dir in specimen_iterator(output_dir):

        staging_info = specimen_dir / 'output' / common.STAGING_INFO_FILENAME

        if not staging_info.is_file():
            raise FileNotFoundError(f'Cannot find staging info file {staging_info}')

        df = pd.read_csv(staging_info, index_col=0)
        df['line'] = line_dir.name
        dataframes.append(df)

    # Write the concatenated staging info to the
    all_staging = pd.concat(dataframes)
    outpath = output_dir / common.STAGING_INFO_FILENAME
    all_staging.to_csv(outpath)

    return all_staging


def annotate(thresholds: pd.DataFrame, lm_results: pd.DataFrame, outdir: Path, line_level: bool = True, label_info: Path = None):
    """
    Using the p_value thresholds and the linear model p-value results,
    create the following CSV fiels

        Line-level results
        specimen-level results

    Parameters
    ----------
    thresholds
        columns label(index), p_thresh, fdr, num_hits_across_all_lines/specimens
    lm_results
        The alternative distribution
        index: line/specimen id
        cols: labels (+ line_id for specimen_level)
    outdir
        The root directory to save the annotated CSV files
    line_level
        if not True, place results in specimen-level sub directory
    label_info
        CSV to map label number to name

    Notes
    -----
    Today's date added to the stats output folder in case it's run multiple times,
    TODO: Add file number prefixes so we don't overwrite mulyiple analyses done on the same day
    TODO: the organ_volumes folder name is hard-coded. What about if we add a new analysis type to the  permutation stats pipeline?
    """

    for id_, row in lm_results.iterrows():

        # Create a dataframe containing p-value column. each organ on rows
        df = row.to_frame()

        if not line_level:
            # specimne-level has an extra line column we need to remove
            df = df.T.drop(columns=['line']).T

        # Rename the line_specimen column to be more informative
        df.rename(columns={id_: GENOTYPE_P_COL_NAME}, inplace=True)

        if line_level:
            line = id_
        else:
            line = row['line']

        # Merge the permutation results (p-thresh, fdr, number of hit lines fo this label) with the mutant results
        df.index = df.index.astype(np.int64)  # Index needs to be cast from object to enable merge
        df = df.merge(thresholds, left_index=True, right_index=True, validate='1:1')
        df.index.name = 'label'

        output_name = f'{id_}_organ_volumes_{str(date.today())}.csv'

        line_output_dir = outdir / line
        line_output_dir.mkdir(exist_ok=True)

        if not line_level:
            # If dealing with specimen-level stats, make subfolder to put results in
            line_output_dir = line_output_dir / 'specimen_level' / id_
            line_output_dir.mkdir(parents=True, exist_ok=True)

        output_path = line_output_dir / output_name

        add_significance(df)

        if label_info:
            df = add_label_names(df , label_info)

        df.to_csv(output_path)


def add_label_names(df: pd.DataFrame, label_info: Path) -> pd.DataFrame:

    label_df = pd.read_csv(label_info, index_col=0)

    df = df.merge(right=label_df[['label_name']], left_index=True, right_index=True)

    return df


def add_significance(df: pd.DataFrame):
    """
    Add a significance column to the output csv in place.
    Set significance to True if the p-value is lower than the threshold and the fdr is under 5%.
    Also sort values by significance
    """
    df[PERM_SIGNIFICANT_COL_NAME] = (df[GENOTYPE_P_COL_NAME] <= df['p_thresh']) & (df['fdr'] <= 0.05)

    df.sort_values(by=[PERM_SIGNIFICANT_COL_NAME, GENOTYPE_P_COL_NAME], ascending=[False, True], inplace=True)


def prepare_data(wt_organ_vol: pd.DataFrame,
                 wt_staging: pd.DataFrame,
                 mut_organ_vol: pd.DataFrame,
                 mut_staging: pd.DataFrame,
                 log_staging: bool = False,
                 log_dependent: bool = False) -> pd.DataFrame:
    """
    Do some pre-processing on the input DataFrames and concatenate into one

    Returns
    -------
    Concatenated data with line, genotype staging + organ volume columns

    """
    wt_staging.rename(columns={'value': 'staging'}, inplace=True)
    mut_staging.rename(columns={'value': 'staging'}, inplace=True)
    wt_staging.index = wt_staging.index.astype(str)


    # merge the organ vol
    organ_vols = pd.concat([wt_organ_vol, mut_organ_vol])

    # Drop any organ columns that has only zero values. These are the gaps in the label map caused by merging labels
    organ_vols = organ_vols.loc[:, (organ_vols != 0).any(axis=0)]

    # For the statsmodels linear mode to work, column names cannot start with a digid. Prefix with 'x'
    organ_vols.columns = [f'x{x}' if x.isdigit() else x for x in organ_vols.columns]

    if log_dependent:
        logging.info('logging dependent variable')
        log_res = np.log(organ_vols.drop(['line'], axis=1))
        line = organ_vols[['line']]
        organ_vols = pd.concat([log_res, line], axis=1)

    # Merge the staging data
    # wt_staging['line'] = 'baseline'
    # mut_staging['line'] = 'mutant'
    staging = pd.concat([wt_staging, mut_staging])

    if log_staging:
        print('logging staging metric')
        log_res = np.log(staging.drop(['line'], axis=1))  # TODO: not finished
        staging = pd.concat([log_res, staging['line']], axis=1)

    # Merge staging to the organvolume dataframe. First drop line so we don't get duplicate entries
    # staging.drop(columns=['line'], inplace=True)

    data = pd.concat([organ_vols, staging], axis=1)

    return data


def run(wt_dir: Path, mut_dir: Path, out_dir: Path, num_perms: int, log_dependent: bool = False, label_info: Path = None):
    """
    Run the premutation-based stats pipeline

    Parameters
    ----------
    wt_dir
        Root of the wild type registration output
        This should contain an 'inputs' folder that contains a single baseline folder that contains multiuple specimen folders
    mut_dir
        Root of the mutant registration output
        This should contain 'inputs' folder that contains multiple mutant lines folder, each containing one or more mutant specimen folders
    out_dir
        Where to store the intermediate results of the permutation testing
    num_perms
        number of permutations to do
    log_dependent
        if True, apply numpy.log to all the dependent values (organ volumes)
    label_info
        if supplied, use it to annotate the results with label names as well as numbers
    """
    # Collate all the staging and organ volume data into csvs

    wt_staging = get_staging_data(wt_dir)
    mut_staging = get_staging_data(mut_dir)

    wt_organ_vol = get_organ_volume_data(wt_dir)
    mut_organ_vol = get_organ_volume_data(mut_dir)

    data = prepare_data(wt_organ_vol,
                        wt_staging,
                        mut_organ_vol,
                        mut_staging,
                        log_dependent)

    out_dir.mkdir(exist_ok=True, parents=True) # Root directory for output

    # make directory to store distributions and thresholds
    dists_out = out_dir / 'distributions'
    dists_out.mkdir(exist_ok=True)

    # Get the null distributions
    line_null, specimen_null = distributions.null(data, num_perms)

    null_line_pvals_file = dists_out / 'null_line_dist_pvalues.csv'
    null_specimen_pvals_file = dists_out / 'null_specimen_dist_pvalues.csv'

    # Write the null distributions to file
    line_null.to_csv(null_line_pvals_file)
    specimen_null.to_csv(null_specimen_pvals_file)

    # Get the alternative distribution
    line_alt, spec_alt = distributions.alternative(data)

    line_alt_pvals_file = dists_out / 'alt_line_dist_pvalues.csv'
    spec_alt_pvals_file = dists_out / 'alt_specimen_dist_pvalues.csv'

    # Write the alternative distributions to file
    line_alt.to_csv(line_alt_pvals_file)
    spec_alt.to_csv(spec_alt_pvals_file)

    line_organ_thresholds = p_thresholds.get_thresholds(line_null, line_alt)
    specimen_organ_thresholds = p_thresholds.get_thresholds(specimen_null, spec_alt)

    line_thresholds_path = dists_out / 'line_organ_p_thresholds.csv'
    spec_thresholds_path = dists_out / 'specimen_organ_p_thresholds.csv'

    line_organ_thresholds.to_csv(line_thresholds_path)
    specimen_organ_thresholds.to_csv(spec_thresholds_path)

    logging.info('Annotating lines')
    # Annotate lines
    annotate(line_organ_thresholds, line_alt, out_dir, label_info=label_info)

    # Annotate specimens
    annotate(specimen_organ_thresholds, spec_alt, out_dir, line_level=False, label_info=label_info)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser("Permutation-based stats")
    parser.add_argument('-w', '--wt_dir', dest='wt_dir', help='wildtype registration directory',
                        type=argparse.FileType('w'),
                        required=True)
    parser.add_argument('-m', '--mut_dir', dest='mut_dir', help='mutant registration directory',
                        type=argparse.FileType('w'),
                        required=True)
    parser.add_argument('-o', '--out_dir', dest='out_dir', help='permutation results directory',
                        type=argparse.FileType('w'),
                        required=True)
    parser.add_argument('-n', '--num_perm', dest='num_perm', help='number of permutations to do', type=np.int,
                        required=False, default=1000)

    args = parser.parse_args()

    run(args.wt_dir, args.mut_dir, args.out_dir, args.num_perm)
