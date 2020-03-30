import os
import functools
import time
import dask
import dask.array as da
from pathlib import Path

import event_model

from ncempy.io import mrc


def _num_t(mrc_obj):
    """ The number of slices in the first dimension (C-ordering)

    """
    # TODO: Alert Peter Ercius that the type returned by dataSize[0] should be `int`
    return int(mrc_obj.dataSize[0])


def _get_slice(mrc_obj, t):
    return mrc_obj.getSlice(t)


@functools.lru_cache(maxsize=10, typed=False)
def _metadata(path):
    with mrc.fileMRC(path) as mrc1:
        pass
    metaData = mrc1.dataOut  # meta data information from the mrc header

    # Save most useful metaData
    metaData = {}
    if hasattr(mrc1, 'FEIinfo'):
        # add in the special FEIinfo if it exists
        metaData.update(mrc1.FEIinfo)

    # Store the X and Y pixel size, offset and unit
    metaData['PhysicalSizeX'] = mrc1.voxelSize[2] * 1e-10  # change Angstroms to meters
    metaData['PhysicalSizeXOrigin'] = 0
    metaData['PhysicalSizeXUnit'] = 'm'
    metaData['PhysicalSizeY'] = mrc1.voxelSize[1] * 1e-10  # change Angstroms to meters
    metaData['PhysicalSizeYOrigin'] = 0
    metaData['PhysicalSizeYUnit'] = 'm'

    metaData['FileName'] = path

    rawtltName = os.path.splitext(path)[0] + '.rawtlt'
    if os.path.isfile(rawtltName):
        with open(rawtltName, 'r') as f1:
            tilts = map(float, f1)
        metaData['tilt angles'] = tilts
    FEIparameters = os.path.splitext(path)[0] + '.txt'
    if os.path.isfile(FEIparameters):
        with open(FEIparameters, 'r') as f2:
            lines = f2.readlines()
        pp1 = list([ii[18:].strip().split(':')] for ii in lines[3:-1])
        pp2 = {}
        for ll in pp1:
            try:
                pp2[ll[0]] = float(ll[1])
            except:
                pass  # skip lines with no data
        metaData.update(pp2)

    return metaData


def ingest_NCEM_MRC(paths):
    assert len(paths) == 1
    path = paths[0]

    # Compose run start
    run_bundle = event_model.compose_run()  # type: event_model.ComposeRunBundle
    start_doc = _metadata(path)
    start_doc.update(run_bundle.start_doc)
    start_doc["sample_name"] = Path(paths[0]).resolve().stem
    yield 'start', start_doc

    mrc_handle = mrc.fileMRC(path)
    num_t = _num_t(mrc_handle)
    first_frame = _get_slice(mrc_handle, 0)
    shape = first_frame.shape
    dtype = first_frame.dtype

    delayed_get_slice = dask.delayed(_get_slice)
    dask_data = da.stack([da.from_delayed(delayed_get_slice(mrc_handle, t), shape=shape, dtype=dtype)
                          for t in range(num_t)])

    # Compose descriptor
    source = 'NCEM'
    frame_data_keys = {'raw': {'source': source,
                               'dtype': 'number',
                               'shape': (num_t, *shape)}}
    frame_stream_name = 'primary'
    frame_stream_bundle = run_bundle.compose_descriptor(data_keys=frame_data_keys,
                                                        name=frame_stream_name,
                                                        # configuration=_metadata(path)
                                                        )
    yield 'descriptor', frame_stream_bundle.descriptor_doc

    # NOTE: Resource document may be meaningful in the future. For transient access it is not useful
    # # Compose resource
    # resource = run_bundle.compose_resource(root=Path(path).root, resource_path=path, spec='NCEM_DM', resource_kwargs={})
    # yield 'resource', resource.resource_doc

    # Compose datum_page
    # z_indices, t_indices = zip(*itertools.product(z_indices, t_indices))
    # datum_page_doc = resource.compose_datum_page(datum_kwargs={'index_z': list(z_indices), 'index_t': list(t_indices)})
    # datum_ids = datum_page_doc['datum_id']
    # yield 'datum_page', datum_page_doc

    yield 'event', frame_stream_bundle.compose_event(data={'raw': dask_data},
                                                     timestamps={'raw': time.time()})

    yield 'stop', run_bundle.compose_stop()


if __name__ == "__main__":
    print(list(ingest_NCEM_MRC(["/home/rp/data/NCEM/Te_80k_L100mm_80Kx(1).mrc"])))
