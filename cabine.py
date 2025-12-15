import ezdxf

doc = ezdxf.new(dxfversion="R2010")
msp = doc.modelspace()

# === DIMENSÕES EM METROS ===
ESCALA = 100  # converter para cm

# CAMADAS
for layer in ["CUBICULOS", "TRANSFORMADOR", "ATERRAMENTO", "QGBT", "TEXTO"]:
    if layer not in doc.layers:
        doc.layers.add(name=layer)


def add_text(label: str, insert: tuple[float, float], height: float = 20, layer: str = "TEXTO") -> None:
    msp.add_text(label, dxfattribs={"height": height, "layer": layer, "insert": insert})


# --- Cubículos ---
def desenha_cubiculo(x: float, nome: str) -> float:
    largura = 2 * ESCALA
    altura = 3 * ESCALA
    msp.add_lwpolyline(
        [(x, 0), (x, altura), (x + largura, altura), (x + largura, 0), (x, 0)],
        dxfattribs={"layer": "CUBICULOS"},
    )
    add_text(nome, (x + 20, altura + 20))
    return x + largura + 20  # devolve posição sugerida para próximo item


x_pos = 0
for nome in ["Cubículo Entrada", "Cub. Medição", "Cub. Proteção"]:
    x_pos = desenha_cubiculo(x_pos, nome)

# --- Transformador ---
trafo_x = x_pos
trafo_w = 250
trafo_h = 300
msp.add_lwpolyline(
    [
        (trafo_x, 0),
        (trafo_x, trafo_h),
        (trafo_x + trafo_w, trafo_h),
        (trafo_x + trafo_w, 0),
        (trafo_x, 0),
    ],
    dxfattribs={"layer": "TRANSFORMADOR"},
)
add_text("Trafo 225 kVA", (trafo_x + 20, trafo_h + 30))
add_text("15/0.38 kV", (trafo_x + 20, trafo_h + 10))

# --- QGBT ---
qgbt_x = trafo_x + trafo_w + 30
qgbt_w = 200
qgbt_h = 250
msp.add_lwpolyline(
    [
        (qgbt_x, 0),
        (qgbt_x, qgbt_h),
        (qgbt_x + qgbt_w, qgbt_h),
        (qgbt_x + qgbt_w, 0),
        (qgbt_x, 0),
    ],
    dxfattribs={"layer": "QGBT"},
)
add_text("QGBT", (qgbt_x + 30, qgbt_h + 20))

# --- Aterramento (Malha com hastes de 3m a cada 1m) ---
for i in range(9):
    x = i * 100
    y = -150 if i % 2 == 0 else -200
    msp.add_circle((x, y), radius=5, dxfattribs={"layer": "ATERRAMENTO"})
    add_text(f"Haste {i+1}", (x - 20, y - 20), height=10)

# --- Salvar ---
doc.saveas("projeto_subestacao_15kv_blindada.dxf")
print("✅ Projeto gerado com sucesso: projeto_subestacao_15kv_blindada.dxf")
