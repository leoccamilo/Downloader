"""Regressions for physical sites and per-cell PSCell frequency resolution."""
import ast
import json
from pathlib import Path
import unittest

import pandas as pd

from bundled_sources import AUDIT_SCRIPTS


class PSCellRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cells = json.loads((AUDIT_SCRIPTS / 'Audit_PSCellChange_v10.ipynb').read_text(encoding='utf-8'))['cells']
        tree = ast.parse(''.join(cls.cells[1]['source']))
        # Load embedded functions without opening production input files.
        tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
                     or isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id != 'coordenadas' for t in node.targets)]
        cls.rules = {}
        exec(compile(tree, 'pscell-rules', 'exec'), cls.rules)

    def test_hotel_cells_use_physical_site_and_malformed_names_use_host(self):
        cell = pd.Series(['ZABC11', 'ZDEF12', '1234567890'])
        host = pd.Series(['MABC1_AM'] * 3)
        self.assertEqual(self.rules['site_lte'](cell, host).tolist(), ['AMABC', 'AMDEF', 'AMABC'])
        nr = pd.Series(['5SDEF13', '1234567890'])
        self.assertEqual(self.rules['site_nr'](nr, host.iloc[:2]).tolist(), ['AMDEF', 'AMABC'])

    def test_sector_mapping_preserves_zero_and_maps_carriers(self):
        cells = pd.Series(['ZABC1', 'ZABC4', 'ZABC7', 'ZABC5', 'ZABC9', 'ZABC0', 'bad'])
        self.assertEqual(self.rules['sector'](cells).tolist(), [1, 1, 1, 2, 3, 0, 0])

    def test_frequency_join_does_not_borrow_another_cells_id(self):
        namespace = dict(self.rules, semana_atual=46)
        from unittest.mock import patch
        freq = pd.DataFrame(dict(UF=['AM', 'AM'], eNB=['MABC1_AM'] * 2,
                                 EUtranCellTDD=['TABC11', 'TABC13'],
                                 GUtranFrequency=[627360] * 2,
                                 GUtranSyncSignalFrequency=['30'] * 2,
                                 GUtranFreqRelationId=['NR_627360', '627360-30']))
        namespace['_gfreq_cell_column'] = lambda path: 'EUtranCellTDD'
        with patch.object(pd, 'read_csv', return_value=freq):
            exec(''.join(self.cells[33]['source']), namespace)
        namespace['lte_nr'] = pd.DataFrame(dict(UF=['AM'], eNB=['MABC1_AM'], CELL=['TABC11'], ssbFrequency=[627360]))
        exec(''.join(self.cells[34]['source']), namespace)
        self.assertEqual(namespace['lte_nr1']['GUtranFreqRelationId'].tolist(), ['NR_627360'])

    def test_missing_cell_scope_fails_instead_of_using_node_scope(self):
        namespace = dict(self.rules, semana_atual=46)
        namespace['_gfreq_cell_column'] = lambda path: ''
        with self.assertRaisesRegex(ValueError, 'sem coluna de celula'):
            exec(''.join(self.cells[33]['source']), namespace)

    def test_distance_uses_two_physical_sites(self):
        frame = pd.DataFrame({'src': ['AMABC'], 'tgt': ['AMDEF']})
        coordinates = pd.DataFrame({'Site': ['AMABC', 'AMDEF'], 'Latitude': [0., 0.], 'Longitude': [0., 1.]})
        out = self.rules['_add_distance'](frame, coordinates, 'src', 'tgt')
        self.assertAlmostEqual(out['Distance'].iloc[0], 111.2, places=2)

    def test_missing_coordinates_stay_unknown_instead_of_becoming_zero(self):
        frame = pd.DataFrame({'src': ['AMABC'], 'tgt': ['AMDEF']})
        coordinates = pd.DataFrame({'Site': ['AMABC'], 'Latitude': [0.], 'Longitude': [0.]})
        out = self.rules['_add_distance'](frame, coordinates, 'src', 'tgt')
        self.assertTrue(pd.isna(out['Distance'].iloc[0]))

    def test_configured_external_lookup_includes_plmn(self):
        from unittest.mock import patch
        namespace = dict(self.rules)
        namespace['missing_5g_4g_mob'] = pd.DataFrame({
            'UF': ['AM', 'AM'], 'gNB': ['MABC1_AM'] * 2,
            'NRCellCU': ['5SABC11'] * 2, 'eNB': ['MDEF1_AM'] * 2,
            'CELL': ['ZDEF11'] * 2, 'CGI': ['72411-1001-1', '72499-1001-1']})
        namespace['NRCellDU3'] = pd.DataFrame({'gNB': ['MABC1_AM'], 'NRCellCU': ['5SABC11'], 'cellLocalId': [1]})
        namespace['coordenadas'] = pd.DataFrame(columns=['Site', 'Latitude', 'Longitude'])
        external = pd.DataFrame({'eNB': ['MABC1_AM'] * 2, 'eNodeBId': [1001] * 2,
                                 'pLMNId_mcc': [724] * 2, 'pLMNId_mnc': [11, 99],
                                 'externalENodeBFunctionId': ['configured_11', 'configured_99']})
        tree = ast.parse(''.join(self.cells[55]['source']))
        tree.body = [node for node in tree.body if not (isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                     and node.value.func.attr == 'to_excel')]
        with patch.object(pd, 'read_csv', return_value=external):
            exec(compile(tree, 'external-plmn-regression', 'exec'), namespace)
        result = namespace['missing_5g_4g_mob']
        self.assertEqual(len(result), 2)
        self.assertEqual(result['externalENodeBFunctionId_MO'].tolist(), ['configured_11', 'configured_99'])


if __name__ == '__main__':
    unittest.main()
