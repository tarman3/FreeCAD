# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2022 FreeCAD Project Association                        *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

import Draft
import FreeCAD
import FreeCADGui
import Part
import Path
import Path.Op.Base as OpBase
import PathScripts.PathUtils as PathUtils
from Path.Dressup.Utils import toolController

from PySide.QtCore import QT_TRANSLATE_NOOP

import math
import time

__title__ = "CAM Path Compound with Tool Controller"
__author__ = ""
__url__ = ""
__doc__ = ""


if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


translate = FreeCAD.Qt.translate


class ObjectCompound:
    def __init__(self, obj):
        # obj.addProperty(
        #     "App::PropertyLinkList",
        #     "Group",
        #     "Path",
        #     QT_TRANSLATE_NOOP("App::Property", "The toolpath(s) to compound"),
        # )
        obj.addProperty(
            "App::PropertyBool",
            "Active",
            "Path",
            QT_TRANSLATE_NOOP(
                "App::Property", "Make False, to prevent operation from generating code"
            ),
        )
        obj.addProperty(
            "App::PropertyString",
            "Comment",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "An optional comment for this Operation"),
        )
        obj.addProperty(
            "App::PropertyString",
            "UserLabel",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "User Assigned Label"),
        )
        obj.addProperty(
            "App::PropertyLink",
            "ToolController",
            "Path",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The tool controller that will be used to calculate the path",
            ),
        )
        obj.addProperty(
            "App::PropertyString",
            "CycleTime",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "Operations Cycle Time Estimation"),
        )
        obj.Active = True
        obj.Proxy = self
        obj.setEditorMode("CycleTime", 1)  # read-only

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onChanged(self, obj, prop):
        pass

    def onDocumentRestored(self, obj):
        """onDocumentRestored(obj) ... Called automatically when document is restored."""

        if not hasattr(obj, "Active"):
            obj.addProperty(
                "App::PropertyBool",
                "Active",
                "Path",
                QT_TRANSLATE_NOOP(
                    "PathOp", "Make False, to prevent operation from generating code"
                ),
            )
            obj.Active = True

    def execute(self, obj):
        if isinstance(obj.Group, list):
            group = obj.Group

        if len(group) == 0:
            return

        obj.ToolController = toolController(group[0])

        # Do not generate paths and clear current Path data if operation not
        if not obj.Active:
            if obj.Path:
                obj.Path = Path.Path()
            return

        obj.Path = Compound(obj.Group).getPath()
        obj.CycleTime = self.getCycleTimeEstimate(obj)
        # self.job.Proxy.getCycleTime()

    def getCycleTimeEstimate(self, obj):

        tc = obj.ToolController

        if tc is None or tc.ToolNumber == 0:
            Path.Log.error(translate("CAM", "No Tool Controller selected."))
            return translate("CAM", "Tool Error")

        hFeedrate = tc.HorizFeed.Value
        vFeedrate = tc.VertFeed.Value
        hRapidrate = tc.HorizRapid.Value
        vRapidrate = tc.VertRapid.Value

        if (hFeedrate == 0 or vFeedrate == 0) and not Path.Preferences.suppressAllSpeedsWarning():
            Path.Log.warning(
                translate(
                    "CAM",
                    "Tool Controller feedrates required to calculate the cycle time.",
                )
            )
            return translate("CAM", "Feedrate Error")

        if (
            hRapidrate == 0 or vRapidrate == 0
        ) and not Path.Preferences.suppressRapidSpeedsWarning():
            Path.Log.warning(
                translate(
                    "CAM",
                    "Add Tool Controller Rapid Speeds on the SetupSheet for more accurate cycle times.",
                )
            )

        # Get the cycle time in seconds
        seconds = obj.Path.getCycleTime(hFeedrate, vFeedrate, hRapidrate, vRapidrate)

        if not seconds or math.isnan(seconds):
            return translate("CAM", "Cycletime Error")

        # Convert the cycle time to a HH:MM:SS format
        cycleTime = time.strftime("%H:%M:%S", time.gmtime(seconds))

        return cycleTime


class Compound:
    def __init__(self, GroupList):
        self.GroupList = list()

        if GroupList:
            if isinstance(GroupList, list):
                self.GroupList = GroupList
            else:
                self.GroupList = [GroupList]

    # Public method
    def getPath(self):
        """getPath() ... Call this method on an instance of the class to generate and return
        path data for the requested path array."""

        output = ""
        base = self.GroupList
        for b in base:
            np = Path.Path(b.Path.Commands)
            output += np.toGCode()

        # return output
        return Path.Path(output)


class ViewProviderArray:
    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        return

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def claimChildren(self):
        if hasattr(self, "Object"):
            if hasattr(self.Object, "Base"):
                if self.Object.Base:
                    return self.Object.Base
        return []


class commandPathCompoundTC:
    def GetResources(self):
        return {
            "Pixmap": "CAM_CompoundTC",
            "MenuText": QT_TRANSLATE_NOOP("CAM_PathCompoundTC", "Path Compound TC"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_PathCompoundTC", "Creates compound of paths with tool controller"
            ),
        }

    def IsActive(self):
        selections = [
            sel.isDerivedFrom("Path::Feature") for sel in FreeCADGui.Selection.getSelection()
        ]
        return selections and all(selections)

    def Activated(self):
        doc = FreeCAD.ActiveDocument

        FreeCAD.ActiveDocument.openTransaction("Create Array")

        compoundObj = doc.addObject("Path::FeatureCompoundPython", "PathCompound")
        ObjectCompound(compoundObj)
        selection = FreeCADGui.Selection.getSelection()
        groupObjs = [obj for obj in selection if isinstance(obj.Proxy, Path.Op.Base.ObjectOp)]
        compoundObj.Group = groupObjs
        PathUtils.addToJob(compoundObj)
        compoundObj.ViewObject.Proxy = 0

        # PathUtils.getToolControllers = _getToolControllers
        # _addBaseProperties(compoundObj)
        # _addToolController(compoundObj, groupObjs)
        FreeCAD.ActiveDocument.commitTransaction()
        doc.recompute()


if FreeCAD.GuiUp:
    # register the FreeCAD command
    FreeCADGui.addCommand("CAM_PathCompoundTC", commandPathCompoundTC())
