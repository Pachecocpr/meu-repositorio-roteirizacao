import streamlit as st
import pandas as pd
from sklearn.cluster import KMeans
import plotly.express as px
from io import BytesIO
import numpy as np
from geopy.geocoders import Nominatim
import time
import random

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Roteirização por Unidades", page_icon="📍", layout="wide")

# --- FUNÇÕES TÉCNICAS OTIMIZADAS ---
def limpar_texto_endereco(texto):
    if not texto or pd.isna(texto):
        return ""
    t = str(texto).lower()
    termos_para_remover = ["bairro ", "sala ", "apto ", "bloco ", "casa ", "loja ", "galpão ", "gp ", "br-"]
    for termo in termos_para_remover:
        t = t.replace(termo, " ")
    return t.strip()

def buscar_coordenadas(local, cache_local):
    if not local or pd.isna(local) or str(local).strip() in ["", "nan"]: 
        return None, None
    
    local_str = str(local).strip()
    if local_str in cache_local:
        return cache_local[local_str]
        
    try:
        agente = f"rot_unidades_{random.randint(1000, 9999)}"
        geolocator = Nominatim(user_agent=agente, timeout=12)
        location = geolocator.geocode(f"{local_str}, Minas Gerais, Brazil")
        
        if location:
            coordenadas = (location.latitude, location.longitude)
            cache_local[local_str] = coordenadas
            time.sleep(1.1) 
            return coordenadas
    except:
        pass
        
    return None, None

def calcular_distancia(lat1, lon1, lat2, lon2):
    r = 6371 
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi, dlambda = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2)**2
    return (2 * r * np.arcsin(np.sqrt(a))) * 1.3

def formatar_tempo(km):
    horas = km / 60
    return f"{int(horas//1)}h {int((horas%1)*60)}min"

def ordenar_por_proximidade(lat_inicio, lon_inicio, pontos_df):
    df_copia = pontos_df.copy()
    rota_ordenada = []
    lat_atual, lon_atual = lat_inicio, lon_inicio
    
    while not df_copia.empty:
        df_copia['dist_provisoria'] = df_copia.apply(
            lambda r: calcular_distancia(lat_atual, lon_atual, r['lat'], r['lon']), axis=1
        )
        idx_mais_proximo = df_copia['dist_provisoria'].idxmin()
        ponto_escolhido = df_copia.loc[idx_mais_proximo]
        
        rota_ordenada.append(ponto_escolhido)
        lat_atual, lon_atual = ponto_escolhido['lat'], ponto_escolhido['lon']
        df_copia = df_copia.drop(idx_mais_proximo)
        
    return pd.DataFrame(rota_ordenada)

# --- INTERFACE ---
st.title("🚚 ROTEIRIZAÇÃO POR UNIDADES")
st.markdown("Defina o ponto de partida, carregue a planilha de destinos e otimize as rotas da sua frota.")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Configurações de Partida")

endereco_input = st.sidebar.text_input(
    "Digite o endereço completo de partida:", 
    value="Belo Horizonte - MG", 
    placeholder="Ex: Rua Boaventura, 401, Belo Horizonte - MG"
)

cache_partida = {}
lat_origem, lon_origem = buscar_coordenadas(endereco_input, cache_partida)
if not lat_origem:
    lat_origem, lon_origem = -19.9191, -43.9386 # Padrão BH seguro

st.sidebar.success("📍 **Origem Definida!**")
st.sidebar.divider()
qtd_veiculos = st.sidebar.slider("Quantidade de Veículos Disponíveis:", 1, 20, 3)

# --- CARREGAMENTO DO ARQUIVO XLSX ---
st.sidebar.header("📂 Dados de Destino")
arquivo = st.sidebar.file_uploader("Suba a planilha das Unidades (XLSX)", type=["xlsx"])

if arquivo:
    try:
        # Força o pandas a ler o arquivo ignorando linhas completamente vazias
        df_import = pd.read_excel(arquivo).dropna(how='all')
        
        if df_import.shape[1] < 3:
            st.error("A planilha precisa ter pelo menos 3 colunas populadas.")
            st.stop()
            
        df_final = pd.DataFrame()
        # Capta as 3 primeiras colunas de dados de forma dinâmica (independente do título delas)
        df_final['Unidade solicitante'] = df_import.iloc[:, 0].astype(str)
        df_final['Endereço completo'] = df_import.iloc[:, 1].astype(str)
        df_final['Região'] = df_import.iloc[:, 2].astype(str)
        
        st.info(f"📍 Mapeando coordenadas dos destinos... (Processando {len(df_final)} endereços)")
        barra = st.progress(0)
        lats, lons = [], []
        
        cache_planilha = {}
        
        for i, r in df_final.iterrows():
            # Estratégia 1: Tenta o endereço completo da segunda coluna
            lt, ln = buscar_coordenadas(r['Endereço completo'], cache_planilha)
            
            # Estratégia 2: Se falhar, limpa abreviações/termos poluídos
            if not lt:
                end_limpo = limpar_texto_endereco(r['Endereço completo'])
                lt, ln = buscar_coordenadas(end_limpo, cache_planilha)
                
            # Estratégia 3: Se ainda assim falhar, mapeia pelo nome da Região/Cidade (Coluna 3)
            if not lt:
                lt, ln = buscar_coordenadas(r['Região'], cache_planilha)
                
            # Estratégia 4 (Mecanismo Antifalha): Se tudo der errado, posiciona próximo à origem para não sumir da rota
            if not lt:
                lt, ln = lat_origem + random.uniform(-0.02, 0.02), lon_origem + random.uniform(-0.02, 0.02)
                
            lats.append(lt)
            lons.append(ln)
            barra.progress((i+1)/len(df_final))
            
        df_final['lat'], df_final['lon'] = lats, lons
        
    except Exception as e:
        st.error(f"Erro ao processar o arquivo Excel: {e}")
        st.stop()
else:
    st.info("👋 Aguardando o upload da planilha Excel (.xlsx) na barra lateral para iniciar o planejamento.")
    st.stop()

# --- PROCESSAMENTO DE ROTAS POR VEÍCULO ---
df_final = df_final.dropna(subset=['lat', 'lon'])

if not df_final.empty:
    n_clusters = min(qtd_veiculos, len(df_final))
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df_final['ID_Rota'] = kmeans.fit_predict(df_final[['lat', 'lon']])

    resumo = []
    df_exportar_lista = []
    
    for id_r, gp in df_final.groupby('ID_Rota'):
        gp_ordenado = ordenar_por_proximidade(lat_origem, lon_origem, gp).reset_index(drop=True)
        
        dist = calcular_distancia(lat_origem, lon_origem, gp_ordenado.loc[0, 'lat'], gp_ordenado.loc[0, 'lon'])
        for j in range(len(gp_ordenado)-1):
            dist += calcular_distancia(gp_ordenado.loc[j, 'lat'], gp_ordenado.loc[j, 'lon'], gp_ordenado.loc[j+1, 'lat'], gp_ordenado.loc[j+1, 'lon'])
        dist += calcular_distancia(gp_ordenado.loc[len(gp_ordenado)-1, 'lat'], gp_ordenado.loc[len(gp_ordenado)-1, 'lon'], lat_origem, lon_origem)
        
        gp_ordenado['Veículo Designado'] = id_r + 1
        gp_ordenado['Ordem da Entrega'] = gp_ordenado.index + 1
        df_exportar_lista.append(gp_ordenado)
        
        resumo.append({
            'Veículo': id_r + 1,
            'Qtd Unidades Atendidas': len(gp_ordenado),
            'KM Total Estimado': round(dist, 1),
            'Tempo de Viagem': formatar_tempo(dist),
            'Itinerário Sequencial': ' ➡️ '.join(gp_ordenado['Unidade solicitante'].unique())
        })

    df_detalhado_final = pd.concat(df_exportar_lista, ignore_index=True)

    st.write(f"### 📊 Resumo de Distribuição da Frota ({n_clusters} Veículos Ativos)")
    st.dataframe(pd.DataFrame(resumo), use_container_width=True)
    
    st.write("### 🗺️ Mapa de Rotas e Unidades")
    fig = px.scatter_mapbox(df_detalhado_final, lat="lat", lon="lon", color="Veículo Designado", 
                            hover_name="Unidade solicitante", hover_data=["Endereço completo", "Ordem da Entrega"], zoom=10,
                            color_continuous_scale=px.colors.qualitative.Prism)
    
    fig.add_scattermapbox(lat=[lat_origem], lon=[lon_origem], 
                          marker=dict(size=16, color='red'), name="PONTO DE PARTIDA")
    
    fig.update_layout(mapbox_style="open-street-map", margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig, use_container_width=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(resumo).to_excel(writer, sheet_name="Resumo Frota", index=False)
        colunas_saida = ['Veículo Designado', 'Ordem da Entrega', 'Unidade solicitante', 'Endereço completo', 'Região', 'lat', 'lon']
        df_detalhado_final[colunas_saida].to_excel(writer, sheet_name="Lista de Entregas por Veículo", index=False)
        
    st.download_button(
        label="📥 Baixar Roteirização Completa (XLSX)",
        data=output.getvalue(),
        file_name="roteirizacao_por_unidades.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
