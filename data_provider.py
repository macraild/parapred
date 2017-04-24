import pickle
import pandas as pd
from os.path import isfile
from structure_processor import *

PDBS = "data/pdbs/{0}.pdb"
TRAIN_DATASET_DESC_FILE = "data/abip_train.csv"
TEST_DATASET_DESC_FILE = "data/abip_test.csv"
DATASET_MAX_CDR_LEN = 31  # For padding
DATASET_MAX_AG_LEN = 1269
DATASET_PICKLE = "data.p"


def load_chains(dataset_desc_filename):
    df = pd.read_csv(dataset_desc_filename)
    for _, entry in df.iterrows():
        print("Processing PDB: ", entry['PDB'])

        pdb_name = entry['PDB']
        ab_h_chain = entry['Ab Heavy Chain']
        ab_l_chain = entry['Ab Light Chain']
        ag_chain = entry['Ag']

        structure = get_structure_from_pdb(PDBS.format(pdb_name))
        model = structure[0] # Structure only has one model

        yield model[ag_chain], model[ab_h_chain], model[ab_l_chain], pdb_name


def process_dataset(desc_file):
    num_in_contact = 0
    num_residues = 0

    all_cdrs = []
    all_lbls = []
    all_ags = []

    for ag_chain, ab_h_chain, ab_l_chain, _ in load_chains(desc_file):
        # Sadly, Biopython structures can't be pickled, it seems
        ag_repl, cdrs, lbls, (nic, nr) =\
            process_chains(ag_chain, ab_h_chain, ab_l_chain,
                           max_ag_len=DATASET_MAX_AG_LEN,
                           max_cdr_len=DATASET_MAX_CDR_LEN)

        num_in_contact += nic
        num_residues += nr

        all_cdrs.append(cdrs)
        all_lbls.append(lbls)
        all_ags.append(ag_repl)

    cdrs = np.concatenate(all_cdrs, axis=0)
    lbls = np.concatenate(all_lbls, axis=0)
    ags = np.concatenate(all_ags, axis=0)

    return ags, cdrs, lbls, num_residues / num_in_contact


def compute_entries():
    train_set = process_dataset(TRAIN_DATASET_DESC_FILE)
    test_set = process_dataset(TEST_DATASET_DESC_FILE)
    param_dict = {
        "max_ag_len": DATASET_MAX_AG_LEN,
        "max_cdr_len": DATASET_MAX_CDR_LEN,
        "pos_class_weight": train_set[3]
    }
    return train_set[0:3], test_set[0:3], param_dict  # Hide class weight


def open_dataset():
    if isfile(DATASET_PICKLE):
        print("Precomputed dataset found, loading...")
        with open(DATASET_PICKLE, "rb") as f:
            dataset = pickle.load(f)
    else:
        print("Computing and storing the dataset...")
        dataset = compute_entries()
        with open(DATASET_PICKLE, "wb") as f:
            pickle.dump(dataset, f)

    return dataset


def process_chains(ag_chain, ab_h_chain, ab_l_chain,
                   max_cdr_len, max_ag_len):

    # Extract CDRs
    cdrs = {}
    cdrs.update(extract_cdrs(ab_h_chain, ["H1", "H2", "H3"]))
    cdrs.update(extract_cdrs(ab_l_chain, ["L1", "L2", "L3"]))

    # Compute ground truth -- contact information
    num_residues = 0
    num_in_contact = 0
    contact = {}

    ag_search = NeighborSearch(Selection.unfold_entities(ag_chain, 'A'))

    for cdr_name, cdr_chain in cdrs.items():
        contact[cdr_name] = \
            [residue_in_contact_with(res, ag_search) for res in cdr_chain]
        num_residues += len(contact[cdr_name])
        num_in_contact += sum(contact[cdr_name])

    # Convert Residue entities to amino acid sequences
    cdrs = {k: residue_seq_to_one(v) for k, v in cdrs.items()}
    ag = residue_seq_to_one(ag_chain)

    # Convert to matrices
    # TODO: could simplify with keras.preprocessing.sequence.pad_sequences
    cdr_mats = []
    cont_mats = []
    for cdr_name in ["H1", "H2", "H3", "L1", "L2", "L3"]:
        cdr_chain = cdrs[cdr_name]
        cdr_mat = seq_to_one_hot(cdr_chain)
        cdr_mat_pad = np.zeros((max_cdr_len, NUM_FEATURES))
        cdr_mat_pad[:cdr_mat.shape[0], :] = cdr_mat
        cdr_mats.append(cdr_mat_pad)

        cont_mat = np.array(contact[cdr_name], dtype=float)
        cont_mat_pad = np.zeros((max_cdr_len, 1))
        cont_mat_pad[:cont_mat.shape[0], 0] = cont_mat
        cont_mats.append(cont_mat_pad)

    cdrs = np.stack(cdr_mats)
    lbls = np.stack(cont_mats)

    ag_mat = seq_to_one_hot(ag)
    ag_mat_pad = np.zeros((max_ag_len, NUM_FEATURES))
    ag_mat_pad[:ag_mat.shape[0], :] = ag_mat

    # Replicate AG chain 6 times
    ag_repl = np.resize(ag_mat_pad,
                        (6, ag_mat_pad.shape[0], ag_mat_pad.shape[1]))

    return ag_repl, cdrs, lbls, (num_in_contact, num_residues)
