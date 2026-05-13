from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QRubberBand


class CanvasView(QGraphicsView):
    selectionMade = Signal(QRectF)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._selection_item: QGraphicsRectItem | None = None
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._origin = QPoint()
        self._selecting = False
        self._panning = False
        self._pan_origin = QPoint()
        self._mode = "pan"
        self._zoom = 0
        self.viewport().installEventFilter(self)

    def set_image(self, image_path: str) -> None:
        pixmap = QPixmap(image_path)
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self._selection_item = None
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 0

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    return self._start_pan(event)
                if self._mode == "select":
                    return self._start_selection(event)
            if event.type() == QEvent.Type.MouseMove:
                if self._panning:
                    return self._update_pan(event)
                return self._update_selection(event)
            if event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.RightButton:
                    return self._finish_pan(event)
                return self._finish_selection(event)
        return super().eventFilter(watched, event)

    def _event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _start_selection(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self._pixmap_item is None:
            return False
        self.clear_selection()
        self._origin = self._event_pos(event)
        self._rubber_band.setGeometry(QRect(self._origin, self._origin))
        self._rubber_band.show()
        self._selecting = True
        return True

    def _update_selection(self, event) -> bool:
        if not self._selecting or self._panning:
            return False
        rect = QRect(self._origin, self._event_pos(event)).normalized()
        self._rubber_band.setGeometry(rect)
        return True

    def _finish_selection(self, event) -> bool:
        if not self._selecting or event.button() != Qt.MouseButton.LeftButton:
            return False
        self._rubber_band.hide()
        view_rect = self._rubber_band.geometry().normalized()
        scene_rect = self.mapToScene(view_rect).boundingRect()
        image_rect = self.sceneRect()
        scene_rect = scene_rect.intersected(image_rect)
        self._selecting = False
        if scene_rect.isValid() and scene_rect.width() > 1 and scene_rect.height() > 1:
            self.set_selection_rect(scene_rect)
            self.selectionMade.emit(scene_rect)
        else:
            self.clear_selection()
        return True

    def _start_pan(self, event) -> bool:
        if self._pixmap_item is None:
            return False
        self._panning = True
        self._pan_origin = self._event_pos(event)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        return True

    def _update_pan(self, event) -> bool:
        current = self._event_pos(event)
        delta = current - self._pan_origin
        self._pan_origin = current
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        return True

    def _finish_pan(self, event) -> bool:
        if not self._panning:
            return False
        self._panning = False
        if self._mode == "select":
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        return True

    def set_selection_rect(self, rect: QRectF) -> None:
        pen = QPen(QColor(230, 57, 70), 3)
        brush = QBrush(QColor(230, 57, 70, 70))
        if self._selection_item is None:
            self._selection_item = self.scene().addRect(rect, pen, brush)
            self._selection_item.setZValue(10)
        else:
            self._selection_item.setRect(rect)
            self._selection_item.setPen(pen)
            self._selection_item.setBrush(brush)
        self.ensureVisible(rect, 32, 32)

    def clear_selection(self) -> None:
        if self._selection_item is not None:
            self.scene().removeItem(self._selection_item)
            self._selection_item = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dragMode() == QGraphicsView.DragMode.NoDrag:
            self._origin = self._event_pos(event)
            self._rubber_band.setGeometry(QRect(self._origin, self._origin))
            self._rubber_band.show()
            self._selecting = True
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            rect = QRect(self._origin, self._event_pos(event)).normalized()
            self._rubber_band.setGeometry(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._rubber_band.hide()
            view_rect = self._rubber_band.geometry()
            scene_rect = self.mapToScene(view_rect).boundingRect()
            self._selecting = False
            if scene_rect.isValid() and scene_rect.width() > 1 and scene_rect.height() > 1:
                self.set_selection_rect(scene_rect)
                self.selectionMade.emit(scene_rect)
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self._zoom += 1 if factor > 1 else -1
            self.scale(factor, factor)
            return
        super().wheelEvent(event)

    def set_pan_mode(self) -> None:
        self._mode = "pan"
        self._selecting = False
        self._panning = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def set_select_mode(self) -> None:
        self._mode = "select"
        self._selecting = False
        self._panning = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
