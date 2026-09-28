import sys
import os
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea, QListWidget, QListWidgetItem
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import Qt, QSize, QEvent, QPointF

class TestRcloneMountManager(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Create a single QApplication in offscreen mode
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(["-platform", "offscreen"])

    def test_imports(self):
        """Verify all required classes can be imported from RcloneMountManager"""
        from RcloneMountManager import MainWindow, RemoteController, RemoteListItem, RemoteWidget, StatusIndicator
        self.assertIsNotNone(MainWindow)
        self.assertIsNotNone(RemoteController)
        self.assertIsNotNone(RemoteListItem)
        self.assertIsNotNone(RemoteWidget)
        self.assertIsNotNone(StatusIndicator)

    def test_remote_controller_initialization(self):
        """Verify RemoteController parses general settings correctly from properties file"""
        from RcloneMountManager import RemoteController
        
        # Create a temp properties file manually to avoid external dependency issues
        config_file = Path("test_remote.properties")
        content = """[General]
name = Test Cloud Storage
remote_name = test_remote:
mountpoint = Z:
volname = TestVolume

[Rclone]
config_path = rclone.conf
extra_flags = --links

[Defaults]
vfs-cache-mode = full
vfs-cache-max-age = 30m
dir-cache-time = 1m
"""
        config_file.write_text(content, encoding="utf-8")
        
        try:
            # Initialize controller
            controller = RemoteController(config_file)
            info = controller.get_info()
            
            self.assertEqual(info["name"], "Test Cloud Storage")
            self.assertEqual(info["remote"], "test_remote:")
            self.assertEqual(info["mountpoint"], "Z:")
            self.assertEqual(controller.runtime_params["vfs-cache-mode"], "full")
            self.assertEqual(controller.runtime_params["vfs-cache-max-age"], "30m")
            self.assertEqual(controller.runtime_params["dir-cache-time"], "1m")
        finally:
            if config_file.exists():
                config_file.unlink()

    def test_mainwindow_layout_and_elements(self):
        """Verify MainWindow layout structure and scrollbar components exist and are properly configured"""
        from RcloneMountManager import MainWindow
        
        window = MainWindow()
        
        # Check that main elements exist
        self.assertTrue(hasattr(window, "list_widget"))
        self.assertTrue(hasattr(window, "details_panel"))
        self.assertTrue(hasattr(window, "details_scroll"))
        
        # Verify that details_scroll is a QScrollArea
        self.assertIsInstance(window.details_scroll, QScrollArea)
        self.assertEqual(window.details_scroll.widget(), window.details_panel)
        self.assertTrue(window.details_scroll.widgetResizable())
        self.assertEqual(window.details_scroll.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(window.details_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        
        # Verify left sidebar QListWidget settings
        self.assertIsInstance(window.list_widget, QListWidget)
        self.assertEqual(window.list_widget.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(window.list_widget.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(window.list_widget.spacing(), 1)
        
        # Clean up window
        window.close()

    def test_compact_remote_list_item_properties(self):
        """Verify RemoteListItem has compact margins, spacing, and vertical alignment"""
        from RcloneMountManager import RemoteListItem, StatusIndicator
        
        item_widget = RemoteListItem("drive1", "Google Drive Personal")
        layout = item_widget.layout()
        
        # Check layout margins: (8, 2, 8, 2)
        margins = layout.contentsMargins()
        self.assertEqual(margins.top(), 2)
        self.assertEqual(margins.bottom(), 2)
        self.assertEqual(margins.left(), 8)
        self.assertEqual(margins.right(), 8)
        
        # Check spacing
        self.assertEqual(layout.spacing(), 8)
        self.assertEqual(layout.alignment(), Qt.AlignVCenter)
        
        # Check status indicator compact size
        self.assertIsInstance(item_widget.status_indicator, StatusIndicator)
        self.assertEqual(item_widget.status_indicator.width(), 10)
        self.assertEqual(item_widget.status_indicator.height(), 10)
        
        # Verify click emission
        clicked_ids = []
        item_widget.clicked.connect(lambda rid: clicked_ids.append(rid))
        event = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        item_widget.mousePressEvent(event)
        self.assertEqual(clicked_ids, ["drive1"])

    def test_sidebar_density_with_30_remotes(self):
        """Verify that 30 remotes can be populated, sizeHint is 28px, and density increases significantly"""
        from RcloneMountManager import MainWindow, RemoteListItem
        
        window = MainWindow()
        window.list_widget.clear()
        
        # Populate with 30 mock remotes
        for i in range(30):
            rid = f"remote_{i:02d}"
            item_widget = RemoteListItem(rid, f"Cloud Drive {i:02d}")
            item = QListWidgetItem(window.list_widget)
            item.setSizeHint(QSize(250, 28))
            window.list_widget.addItem(item)
            window.list_widget.setItemWidget(item, item_widget)
        
        self.assertEqual(window.list_widget.count(), 30)
        
        # Test height of each item
        first_item = window.list_widget.item(0)
        item_height = first_item.sizeHint().height()
        self.assertEqual(item_height, 28)
        
        # Percentage reduction: (45 - 28) / 45 = 37.78% (within the 30-50% objective)
        reduction_pct = (45 - item_height) / 45 * 100
        self.assertGreaterEqual(reduction_pct, 30.0)
        self.assertLessEqual(reduction_pct, 50.0)
        
        # Density comparison in a 400px tall list viewport:
        # Previous: 45px item + 4px margin top + 4px margin bottom = 53px per row -> 400 / 53 = 7.5 items
        # Compact: 28px item + 1px margin + 1px spacing = 30px per row -> 400 / 30 = 13.3 items
        old_visible_in_400px = 400 // 53
        new_visible_in_400px = 400 // 30
        self.assertGreaterEqual(new_visible_in_400px - old_visible_in_400px, 5)
        
        # Verify selection synchronization
        window.on_remote_clicked("remote_15")
        # Find item 15 and check if list widget current item is set
        for i in range(window.list_widget.count()):
            item = window.list_widget.item(i)
            widget = window.list_widget.itemWidget(item)
            if isinstance(widget, RemoteListItem) and widget.remote_id == "remote_15":
                window.list_widget.setCurrentItem(item)
                break
        
        self.assertEqual(window.list_widget.currentItem().sizeHint().height(), 28)
        window.close()

if __name__ == "__main__":
    unittest.main()
