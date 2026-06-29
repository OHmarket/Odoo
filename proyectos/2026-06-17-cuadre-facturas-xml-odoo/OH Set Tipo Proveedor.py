# OH Set Tipo Proveedor v1.0  (ir.actions.server / safe_eval)
# Escribe x_studio_tipo_proveedor en proveedores. Match por id de partner.
# Generado desde 'Contacto (res.partner) CORREGIDO.csv'. One-shot.

MAP = {
    'Mercaderia': [269, 271, 278, 280, 282, 285, 286, 287, 289, 291, 293, 294, 295, 297, 298, 299, 300, 301, 305, 306, 307, 315, 316, 464, 465, 466, 470, 472, 474, 477, 537, 674, 679, 687, 693, 720, 804, 838, 876, 948, 987, 1022, 1110, 1141, 1402, 1408, 1427, 1428, 1433, 1434, 1498, 4893, 5100, 5777, 5819, 6158, 6349, 9486, 12619, 13986, 14300, 14304, 14322, 14333, 14347, 14368, 14370, 14396, 14397, 14399, 14420, 14429, 14431, 14432, 14433, 14438, 14457, 14458, 14511, 14517, 14532],
    'Mantención Vehiculos': [526, 644, 695, 749, 858, 1005, 1035, 1327, 1409, 9175, 14325, 14413, 14439, 14470, 14471, 14504, 14512],
    'Viáticos': [645, 646, 659, 691, 4990, 14319],
    'Papelería y Gastos Diversos': [270, 553, 714, 745, 747, 752, 757, 763, 764, 765, 767, 770, 780, 798, 801, 802, 809, 810, 836, 859, 863, 870, 875, 937, 988, 993, 1012, 1021, 1025, 1034, 1113, 1125, 1135, 1139, 1166, 1167, 1182, 1198, 1228, 1294, 1350, 1365, 1371, 1404, 1411, 1414, 1415, 5098, 7365, 7496, 9170, 14299, 14314, 14345, 14372, 14373, 14374, 14405, 14508, 14509],
    'Arriendos Locales': [268, 277, 281, 283, 296, 590, 600, 1007, 1261],
    'Mantención Local': [686, 690, 766, 782, 783, 795, 796, 864, 865, 926, 928, 933, 935, 943, 1010, 1118, 1168, 1219, 1255, 1328, 1410, 1413, 1445, 7495, 14326, 14344, 14348, 14503],
    'Petróleo': [540, 661, 662, 667, 668, 689, 696, 697, 711, 712, 729, 730, 744, 746, 769, 779, 800, 831, 860, 992, 1001, 1013, 1359, 1401, 1448, 6347, 9447, 9947, 14456, 14461],
    'Luz': [530],
    'Internet': [303, 304, 673, 1249, 5082],
    'Metodos de Pago': [276, 309, 548, 12320],
    'Sistemas': [528, 558, 602, 634, 656, 887, 1160, 1161, 5083, 6348],
    'Gastos Bancarios': [311, 312, 314, 612, 613, 14400],
}

P = env['res.partner']
n = 0
faltan = []
for tipo, ids in MAP.items():
    recs = P.browse(ids).exists()
    faltan += [i for i in ids if i not in recs.ids]
    if recs:
        recs.write({'x_studio_tipo_proveedor': tipo})
        n += len(recs)
log('tipo_proveedor seteado en %s proveedores; faltan %s' % (n, faltan))
action = {'type':'ir.actions.client','tag':'display_notification','params':{
    'title':'Tipo proveedor','message':'Seteados %s / faltan %s ids' % (n, len(faltan)),
    'type':'success' if not faltan else 'warning','sticky':True}}