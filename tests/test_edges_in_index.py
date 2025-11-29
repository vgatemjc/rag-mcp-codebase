from server.services.android_plugins import AndroidChunkPlugin, AndroidPayloadPlugin
from server.services.git_aware_code_indexer import Indexer
from server.services.edges import EdgeType, build_edge


class DummyEmbeddings:
    def embed(self, texts):
        return [[0.0]] * len(texts)


class DummyStore:
    def __init__(self):
        self.points = []

    def upsert_points(self, points, batch_size=None):
        self.points.extend(points)


def _collect_edges(store: DummyStore):
    for point in store.points:
        payload = getattr(point, "payload", {}) or {}
        for edge in payload.get("edges", []) or []:
            yield edge


def test_android_edges_attached_in_full_index(git_repo):
    # Arrange sample Android project files.
    git_repo.write(
        "app/src/main/res/navigation/main_nav.xml",
        """
        <navigation xmlns:android="http://schemas.android.com/apk/res/android"
                    xmlns:app="http://schemas.android.com/apk/res-auto"
                    android:id="@+id/main_nav"
                    app:startDestination="@id/home">
          <fragment android:id="@+id/home" android:name="HomeFragment">
            <action android:id="@+id/action_home_to_detail" app:destination="@id/detail"/>
          </fragment>
          <fragment android:id="@+id/detail" android:name="DetailFragment" />
        </navigation>
        """,
    )
    git_repo.write(
        "app/src/main/res/layout/activity_main.xml",
        """
        <layout xmlns:android="http://schemas.android.com/apk/res/android">
          <data>
            <variable name="vm" type="com.example.VM" />
          </data>
          <LinearLayout android:id="@+id/container"/>
        </layout>
        """,
    )
    git_repo.write(
        "app/src/main/java/MainActivity.kt",
        """
        class MainActivity {
            fun onCreate() {
                setContentView(R.layout.activity_main)
                findNavController(R.id.home).navigate(R.id.detail)
                networkService.postData()
            }
        }
        """,
    )
    head = git_repo.commit_all("Add android edge fixtures")

    store = DummyStore()
    emb = DummyEmbeddings()
    payload_plugin = AndroidPayloadPlugin()
    indexer = Indexer(
        repo_path=str(git_repo.path),
        repo_name=git_repo.repo_id,
        embeddings=emb,
        store=store,
        collection="test",
        payload_plugins=[payload_plugin],
        chunk_plugins=[AndroidChunkPlugin()],
        stack_type="android_app",
        edge_plugins=[payload_plugin],
    )

    # Act
    indexer.full_index(head, branch=git_repo.branch)

    # Assert
    edges = list(_collect_edges(store))
    types = {e["type"] for e in edges}
    assert EdgeType.NAV_DESTINATION in types
    assert EdgeType.NAV_ACTION in types
    assert EdgeType.BINDS_LAYOUT in types
    assert EdgeType.NAVIGATES_TO in types
    assert EdgeType.CALLS_API in types
    assert any(e["target"] == "layout/activity_main.xml" for e in edges if e["type"] == EdgeType.BINDS_LAYOUT)
    assert any(e["target"] == "detail" for e in edges if e["type"] == EdgeType.NAV_ACTION)


class StubPayloadPlugin:
    def __init__(self, stack_type="web_frontend"):
        self.stack_type = stack_type

    def build_payload(self, chunk, branch, commit_sha):
        return {"stack_type": self.stack_type, "component_type": "page"}


class StubEdgePlugin:
    def build_edges(self, chunk):
        return [build_edge(EdgeType.NAVIGATES_TO, "home"), build_edge(EdgeType.CALLS_API, "Client.fetch")]


def test_stub_stack_edge_plugin_runs(git_repo):
    git_repo.write("web/index.html", "<a href=\"/home\">Home</a>")
    head = git_repo.commit_all("Add web page")

    store = DummyStore()
    emb = DummyEmbeddings()
    payload_plugin = StubPayloadPlugin()
    indexer = Indexer(
        repo_path=str(git_repo.path),
        repo_name=git_repo.repo_id,
        embeddings=emb,
        store=store,
        collection="test",
        payload_plugins=[payload_plugin],
        chunk_plugins=[],
        stack_type="web_frontend",
        edge_plugins=[StubEdgePlugin()],
    )

    indexer.full_index(head, branch=git_repo.branch)

    edges = list(_collect_edges(store))
    assert any(e["type"] == EdgeType.NAVIGATES_TO for e in edges)
    assert any(e["type"] == EdgeType.CALLS_API for e in edges)
    # Ensure stack typing carried through payload.
    for point in store.points:
        assert point.payload.get("stack_type") == "web_frontend"
