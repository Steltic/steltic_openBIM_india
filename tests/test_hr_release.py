from pathlib import Path

import pytest


def test_hr_audit_requires_each_units_finished_native_report(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'validation' / 'hr'))
    from run_case import require_finished_reports

    units = ('Office', 'Workshop')
    (tmp_path / 'STATUS.engine.md').write_text('Composite status')
    for unit in units:
        folder = tmp_path / 'units' / unit
        (folder / 'design').mkdir(parents=True)
        (folder / 'design' / 'calc_package.json').write_text('{}')
        (folder / 'report.html').write_text('<html><body>Analysis</body></html>')
        (folder / 'STATUS.engine.md').write_text('Final status')

    folder = tmp_path / 'units' / 'Workshop'
    (folder / 'report.html').write_text('<html><body>Analysis in progress')
    with pytest.raises(ValueError, match='native HTML report is unfinished'):
        require_finished_reports(tmp_path, units)
    (folder / 'report.html').write_text('<html><body>Analysis complete</body></html>')
    (folder / 'STATUS.engine.md').unlink()
    with pytest.raises(ValueError, match='STATUS.engine.md'):
        require_finished_reports(tmp_path, units)
    (folder / 'STATUS.engine.md').write_text('Final status')
    require_finished_reports(tmp_path, units)
