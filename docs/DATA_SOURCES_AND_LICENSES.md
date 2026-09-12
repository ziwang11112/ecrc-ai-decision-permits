# Data sources and licensing

This release contains software, synthetic service fixtures and records, and
derived participant- and decision-level behavioural outputs from two public
Iowa Gambling Task datasets. It contains no raw EEG or new participant data.
Source behavioural datasets are obtained separately from their original hosts.

* Development: Steingroever et al. (2015), *Data from 617 Healthy Participants
  Performing the Iowa Gambling Task: A “Many Labs” Collaboration*.
  Data-paper DOI: https://doi.org/10.5334/jopd.ak ; data: https://osf.io/8t7rm/ .
  The **dataset** is CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/ .
  Do not confuse this with the data paper's article licence.
* External replay: Chávez-Sánchez et al. (2026), Mendeley Data **Version 2**,
  https://doi.org/10.17632/2pw2m39yct.2 , under CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/ . Only behavioural IGT files
  contribute to this release.

Transformations include normalisation, historical features, frozen model scores,
policy routes, participant-level counts, resampling estimates and figure inputs.
The derived files retain study/participant/trial keys and proxy labels; they are
not described as aggregate-only or as raw source data. Reuse must preserve source
attribution, identify modifications, and retain applicable source terms.
Consistent with this project's existing licence map, our derived evidence and
figures are distributed under CC BY-SA 4.0. Upstream CC BY material retains its
original licence and attribution. No endorsement by the data creators is implied.

Project software is MIT, with existing copyright and licence notices preserved.
The root LICENSE reproduces the established project licence. The additional
source snapshot licence in reproduce_analysis/experiment_reproducibility/LICENSE
also remains in place. Source-version limitations are documented in iasc/methods/README.md.
The historical training entrypoint hash mismatch has not been resolved by this release.
