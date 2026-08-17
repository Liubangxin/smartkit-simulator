from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DatasetWorkbenchUiTests(unittest.TestCase):
    def test_page_exposes_dataset_workbench_and_merged_runtime_tabs(self):
        with __import__("simulator_gui").app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
        self.assertIn("数据集工作台", html)
        self.assertIn("模拟器运行", html)
        self.assertIn("概览", html)
        self.assertIn("SSH 命令", html)
        self.assertIn("REST 路由", html)
        self.assertIn("关联用例", html)
        self.assertIn("文件信息", html)
        self.assertIn("runtimeOverview", html)
        self.assertNotIn("THROWAWAY PROTOTYPE", html)


if __name__ == "__main__":
    unittest.main()
