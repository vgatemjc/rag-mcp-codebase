from server.services.android_plugins import AndroidChunkPlugin, AndroidPayloadPlugin
from server.services.git_aware_code_indexer import Indexer
from server.services.git_aware_code_indexer import Chunk, Range
from server.services.edges import EdgeType


def _build_payload(chunk):
    idx = Indexer.__new__(Indexer)
    idx.repo_name = "demo"
    idx.base_payload = {}
    idx.payload_plugins = [AndroidPayloadPlugin()]
    return Indexer._build_payload(idx, chunk, "main", "abc123")


def test_manifest_meta_and_payload():
    manifest_src = """
    <manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.demo">
      <application>
        <activity android:name=".MainActivity" android:label="Demo">
          <intent-filter>
            <action android:name="android.intent.action.MAIN"/>
            <category android:name="android.intent.category.LAUNCHER"/>
          </intent-filter>
        </activity>
      </application>
    </manifest>
    """
    plugin = AndroidChunkPlugin()
    chunks = plugin.extra_chunks(manifest_src, "app/src/main/AndroidManifest.xml", "demo")
    assert chunks
    chunk = chunks[0]
    payload = _build_payload(chunk)

    assert chunk.meta.get("kind") == "manifest"
    assert payload["stack_type"] == "android_app"
    assert payload["component_type"] == "manifest"
    assert payload["tags"] == ["manifest"]
    components = payload["stack_meta"]["components"]
    assert components[0]["name"] == ".MainActivity"
    assert "android.intent.action.MAIN" in components[0]["actions"]
    assert payload["stack_text"]


def test_layout_meta_and_payload():
    layout_src = """
    <layout xmlns:android="http://schemas.android.com/apk/res/android">
      <data>
        <variable name="vm" type="com.example.VM" />
      </data>
      <LinearLayout android:id="@+id/container">
        <fragment android:name="com.example.HomeFragment" android:id="@+id/homeFragment"/>
      </LinearLayout>
    </layout>
    """
    plugin = AndroidChunkPlugin()
    chunks = plugin.extra_chunks(layout_src, "app/src/main/res/layout/activity_main.xml", "demo")
    assert chunks
    payload = _build_payload(chunks[0])

    assert payload["component_type"] == "layout"
    assert payload["screen_name"] == "activity_main"
    assert payload["tags"] == ["layout"]
    assert "view_ids" in payload["stack_meta"]
    assert "homefragment" in payload["stack_meta"]["fragment_tags"]
    assert payload["stack_meta"]["viewmodel_class"] == "com.example.VM"
    assert any(edge["type"] == "USES_VIEWMODEL" for edge in payload.get("edges", []))
    assert payload["stack_text"]


def test_navgraph_meta_edges_and_payload():
    nav_src = """
    <navigation xmlns:android="http://schemas.android.com/apk/res/android"
                xmlns:app="http://schemas.android.com/apk/res-auto"
                android:id="@+id/main_nav"
                app:startDestination="@id/home">
      <fragment android:id="@+id/home" android:name="HomeFragment">
        <action android:id="@+id/action_home_to_detail" app:destination="@id/detail"/>
      </fragment>
      <fragment android:id="@+id/detail" android:name="DetailFragment" />
    </navigation>
    """
    plugin = AndroidChunkPlugin()
    chunks = plugin.extra_chunks(nav_src, "app/src/main/res/navigation/main_nav.xml", "demo")
    assert chunks
    payload = _build_payload(chunks[0])

    assert payload["component_type"] == "navgraph"
    assert payload["nav_graph_id"] == "main_nav"
    assert payload["screen_name"] == "main_nav"
    assert payload["tags"] == ["navgraph"]
    assert payload["stack_meta"]["destinations"] == ["detail", "home"]
    assert any(edge["type"] == "NAV_DESTINATION" for edge in payload["edges"])
    assert any(edge["type"] == "NAV_ACTION" for edge in payload["edges"])
    assert payload["stack_text"]


def _code_chunk(content: str, path: str = "app/src/main/java/MainActivity.kt", symbol: str = "class:MainActivity"):
    return Chunk(
        logical_id="demo:" + path + "#" + symbol,
        symbol=symbol,
        path=path,
        language="kotlin",
        range=Range(1, content.count("\n") + 1, 0, len(content)),
        content=content,
        content_hash="hash",
        sig_hash="sig",
    )


def test_binds_layout_and_navigates_to_edges_in_code():
    content = """
    class MainActivity: AppCompatActivity() {
        override fun onCreate() {
            setContentView(R.layout.activity_main)
            findNavController(R.id.nav_host).navigate(R.id.navigation_radio)
            startActivity(Intent(this, DetailActivity::class.java))
        }
    }
    """
    chunk = _code_chunk(content)
    payload = _build_payload(chunk)
    assert any(e["type"] == EdgeType.BINDS_LAYOUT and e["target"] == "layout/activity_main.xml" for e in payload["edges"])
    assert any(e["type"] == EdgeType.NAVIGATES_TO and e["target"] == "navigation_radio" for e in payload["edges"])
    assert any(e["type"] == EdgeType.NAVIGATES_TO and e["target"] == "detailactivity" for e in payload["edges"])


def test_calls_api_edge_in_code():
    content = """
    class Repo {
        fun load() {
            mediaApi.fetchSongs().enqueue()
            networkService.postData()
        }
    }
    """
    chunk = _code_chunk(content, path="app/src/main/java/Repo.kt", symbol="class:Repo")
    payload = _build_payload(chunk)
    assert any(e["type"] == EdgeType.CALLS_API and e["target"] == "mediaApi.fetchSongs" for e in payload["edges"])
    assert any(e["type"] == EdgeType.CALLS_API and e["target"] == "networkService.postData" for e in payload["edges"])
