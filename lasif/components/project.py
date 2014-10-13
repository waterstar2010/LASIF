#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Project components class.

It is important to not import necessary things at the method level to make
importing this file as fast as possible. Otherwise using the command line
interface feels sluggish and slow. Import things only the functions they are
needed.

:copyright: Lion Krischer (krischer@geophysik.uni-muenchen.de), 2013

:license: GNU General Public License, Version 3
    (http://www.gnu.org/copyleft/gpl.html)
"""
from __future__ import absolute_import

import cPickle
import os

from lasif import LASIFError
import lasif.domain

from .actions import ActionsComponent
from .adjoint_sources import AdjointSourcesComponent
from .communicator import Communicator
from .component import Component
from .downloads import DownloadsComponent
from .events import EventsComponent
from .inventory_db import InventoryDBComponent
from .iterations import IterationsComponent
from .kernels import KernelsComponent
from .models import ModelsComponent
from .query import QueryComponent
from .stations import StationsComponent
from .validator import ValidatorComponent
from .visualizations import VisualizationsComponent
from .waveforms import WaveformsComponent
from .windows import WindowsComponent


class Project(Component):
    """
    A class managing LASIF projects.

    It represents the heart of LASIF.
    """
    def __init__(self, project_root_path, init_project=False):
        """
        Upon intialization, set the paths and read the config file.

        :type project_root_path: str
        :param project_root_path: The root path of the project.
        :type init_project: str
        :param init_project: Determines whether or not to initialize a new
            project, e.g. create the necessary folder structure. If a string is
            passed, the project will be given this name. Otherwise a default
            name will be chosen. Defaults to False.
        """
        # Setup the paths.
        self.__setup_paths(project_root_path)

        if init_project:
            if not os.path.exists(project_root_path):
                os.makedirs(project_root_path)
            self.__init_new_project(init_project)

        if not os.path.exists(self.paths["config_file"]):
            msg = ("Could not find the project's config file. Wrong project "
                   "path or uninitialized project?")
            raise LASIFError(msg)

        # Setup the communicator and register this component.
        self.__comm = Communicator()
        super(Project, self).__init__(self.__comm, "project")
        # Setup the different components.
        self.__setup_components()

        # Finally update the folder structure.
        self.__update_folder_structure()

        self._read_config_file()

    def __str__(self):
        """
        Pretty string representation.
        """
        from lasif.utils import sizeof_fmt
        # Count all files and sizes.

        raw_data_file_count = 0
        processed_data_file_count = 0
        synthetic_data_file_count = 0
        station_file_count = 0
        project_filesize = 0

        for dirpath, _, filenames in os.walk(self.paths["root"]):
            size = sum([os.path.getsize(os.path.join(dirpath, _i))
                        for _i in filenames])
            project_filesize += size
            if dirpath.startswith(self.paths["data"]):
                if dirpath.endswith("raw"):
                    raw_data_file_count += len(filenames)
                elif "processed" in dirpath:
                    processed_data_file_count += len(filenames)
            elif dirpath.startswith(self.paths["synthetics"]):
                synthetic_data_file_count += len(filenames)
            elif dirpath.startswith(self.paths["stations"]):
                station_file_count += len(filenames)

        ret_str = "LASIF project \"%s\"\n" % self.config["name"]
        ret_str += "\tDescription: %s\n" % self.config["description"]
        ret_str += "\tProject root: %s\n" % self.paths["root"]
        ret_str += "\tContent:\n"
        ret_str += "\t\t%i events\n" % self.comm.events.count()
        ret_str += "\t\t%i station files\n" % station_file_count
        ret_str += "\t\t%i raw waveform files\n" % raw_data_file_count
        ret_str += "\t\t%i processed waveform files \n" % \
                   processed_data_file_count
        ret_str += "\t\t%i synthetic waveform files\n" % \
                   synthetic_data_file_count

        ret_str += "\tTotal project size: %s\n\n" % \
                   sizeof_fmt(project_filesize)

        d = str(self.domain)
        ret_str += "\n".join(["\t" + i for i in d.splitlines()])

        return ret_str

    def _read_config_file(self):
        """
        Parse the config file.
        """
        # Needed to transition from old config files to new config files.
        default_download_settings = {
            "seconds_before_event": 100.0,
            "seconds_after_event": 3600.0,
            "interstation_distance_in_m": 1000.0,
            "channel_priorities": ["BH[Z,N,E]", "LH[Z,N,E]", "HH[Z,N,E]",
                                   "EH[Z,N,E]", "MH[Z,N,E]"],
            "location_priorities": ["", "00", "10", "20", "01", "02"]
        }

        # Attempt to read the cached config file. This might seem excessive but
        # since this file is read every single time a LASIF command is used it
        # makes difference at least in the perceived speed of LASIF.
        cfile = self.paths["config_file_cache"]
        if os.path.exists(cfile):
            try:
                with open(cfile, "rb") as fh:
                    cf_cache = cPickle.load(fh)
                last_m_time = int(os.path.getmtime(self.paths["config_file"]))
                if last_m_time == cf_cache["last_m_time"]:
                    default_download_settings.update(cf_cache["config"][
                        "download_settings"])
                    self.config = cf_cache["config"]
                    self.config["download_settings"] = \
                        default_download_settings
                    self.domain = cf_cache["domain"]
                    # XXX: Only until migration to new LASIF version happened.
                    if isinstance(self.domain, dict):
                        os.remove(cfile)
                    else:
                        return
            except:
                os.remove(cfile)

        from lxml import etree
        root = etree.parse(self.paths["config_file"]).getroot()

        self.config = {}
        self.config["name"] = root.find("name").text
        self.config["description"] = root.find("description").text
        # The description field is the only field allowed to be empty.
        if self.config["description"] is None:
            self.config["description"] = ""

        self.config["download_settings"] = default_download_settings
        dl_settings = root.find("download_settings")
        self.config["download_settings"]["seconds_before_event"] = \
            float(dl_settings.find("seconds_before_event").text)
        self.config["download_settings"]["seconds_after_event"] = \
            float(dl_settings.find("seconds_after_event").text)
        # Only add if available, otherwise use defaults.
        dist = dl_settings.find('interstation_distance_in_m')
        if dist is not None:
            self.config["download_settings"]["interstation_distance_in_m"] = \
                float(dist.text)
        c_p = dl_settings.find("channel_priorities")
        if c_p is not None:
            self.config["download_settings"]["channel_priorities"] = \
                [str(_i.text) if _i.text else ""
                 for _i in c_p.findall("priority")]
        l_p = dl_settings.find("location_priorities")
        if l_p is not None:
            self.config["download_settings"]["location_priorities"] = \
                [str(_i.text) if _i.text else ""
                 for _i in l_p.findall("priority")]

        # Read the domain.
        domain = root.find("domain")

        # Check if the domain is global.
        is_global = domain.find("global")
        if is_global is not None and is_global.text.strip().lower() == "true":
            self.domain = lasif.domain.GlobalDomain()
        else:
            bounds = domain.find("domain_bounds")
            rotation = domain.find("domain_rotation")
            self.domain = lasif.domain.RectangularSphericalSection(
                min_longitude=float(bounds.find("minimum_longitude").text),
                max_longitude=float(bounds.find("maximum_longitude").text),
                min_latitude=float(bounds.find("minimum_latitude").text),
                max_latitude=float(bounds.find("maximum_latitude").text),
                min_depth_in_km=float(bounds.find("minimum_depth_in_km").text),
                max_depth_in_km=float(bounds.find("maximum_depth_in_km").text),
                rotation_axis=[
                    float(rotation.find("rotation_axis_x").text),
                    float(rotation.find("rotation_axis_y").text),
                    float(rotation.find("rotation_axis_z").text)],
                rotation_angle_in_degree=float(
                    rotation.find("rotation_angle_in_degree").text),
                boundary_width_in_degree=float(
                    bounds.find("boundary_width_in_degree").text))

        # Write cache file.
        cf_cache = {}
        cf_cache["config"] = self.config
        cf_cache["domain"] = self.domain
        cf_cache["last_m_time"] = \
            int(os.path.getmtime(self.paths["config_file"]))
        with open(cfile, "wb") as fh:
            cPickle.dump(cf_cache, fh, protocol=2)

    def get_filecounts_for_event(self, event_name):
        """
        Gets the number of files associated with the current event.

        :type event_name: str
        :param event_name: The name of the event.

        :rtype: dict
        :returns: A dictionary with the following self-explaining keys:
            * raw_waveform_file_count
            * synthetic_waveform_file_count
            * preprocessed_waveform_file_count
        """
        # Make sure the event exists.
        if not self.comm.events.has_event(event_name):
            msg = "Event '%s' not found in project." % event_name
            raise ValueError(msg)

        data_path = os.path.join(self.paths["data"], event_name)
        synth_path = os.path.join(self.paths["synthetics"], event_name)
        raw_data_count = 0
        processed_data_count = 0
        synthetic_data_count = 0
        for dirpath, _, filenames in os.walk(data_path):
            if dirpath.endswith("raw"):
                raw_data_count += len(filenames)
            elif "preprocessed" in dirpath:
                processed_data_count += len(filenames)
        for dirpath, _, filenames in os.walk(synth_path):
            synthetic_data_count += len(filenames)
        return {
            "raw_waveform_file_count": raw_data_count,
            "synthetic_waveform_file_count": synthetic_data_count,
            "preprocessed_waveform_file_count": processed_data_count}

    def get_communicator(self):
        return self.__comm

    def __setup_components(self):
        """
        Setup the different components of the project. The goal is to
        decouple them as much as possible to keep the structure sane and
        maintainable.

        Communication will happen through the communicator which will also
        keep the references to the single components.
        """
        # Basic components.
        EventsComponent(folder=self.paths["events"], communicator=self.comm,
                        component_name="events")
        StationsComponent(stationxml_folder=self.paths["station_xml"],
                          seed_folder=self.paths["dataless_seed"],
                          resp_folder=self.paths["resp"],
                          cache_folder=self.paths["cache"],
                          communicator=self.comm, component_name="stations")
        WaveformsComponent(data_folder=self.paths["data"],
                           synthetics_folder=self.paths["synthetics"],
                           communicator=self.comm, component_name="waveforms")
        InventoryDBComponent(db_file=self.paths["inv_db_file"],
                             communicator=self.comm,
                             component_name="inventory_db")
        ModelsComponent(models_folder=self.paths["models"],
                        communicator=self.comm,
                        component_name="models")
        KernelsComponent(kernels_folder=self.paths["kernels"],
                         communicator=self.comm,
                         component_name="kernels")
        IterationsComponent(iterations_folder=self.paths["iterations"],
                            communicator=self.comm,
                            component_name="iterations")

        # Action and query components.
        QueryComponent(communicator=self.comm, component_name="query")
        VisualizationsComponent(communicator=self.comm,
                                component_name="visualizations")
        ActionsComponent(communicator=self.comm,
                         component_name="actions")
        ValidatorComponent(communicator=self.comm,
                           component_name="validator")

        # Window and adjoint source components.
        WindowsComponent(windows_folder=self.paths["windows"],
                         communicator=self.comm,
                         component_name="windows")
        AdjointSourcesComponent(ad_src_folder=self.paths["adjoint_sources"],
                                communicator=self.comm,
                                component_name="adjoint_sources")

        # Data downloading component.
        DownloadsComponent(communicator=self.comm,
                           component_name="downloads")

    def __setup_paths(self, root_path):
        """
        Central place to define all paths.
        """
        # Every key containing the string "file" denotes a file, all others
        # should denote directories.
        self.paths = {}
        self.paths["root"] = root_path

        self.paths["events"] = os.path.join(root_path, "EVENTS")
        self.paths["data"] = os.path.join(root_path, "DATA")
        self.paths["cache"] = os.path.join(root_path, "CACHE")
        self.paths["logs"] = os.path.join(root_path, "LOGS")
        self.paths["models"] = os.path.join(root_path, "MODELS")
        self.paths["wavefields"] = os.path.join(root_path, "WAVEFIELDS")
        self.paths["iterations"] = os.path.join(root_path, "ITERATIONS")
        self.paths["synthetics"] = os.path.join(root_path, "SYNTHETICS")
        self.paths["kernels"] = os.path.join(root_path, "KERNELS")
        self.paths["stations"] = os.path.join(root_path, "STATIONS")
        self.paths["output"] = os.path.join(root_path, "OUTPUT")

        self.paths["windows"] = os.path.join(
            root_path, "ADJOINT_SOURCES_AND_WINDOWS", "WINDOWS")
        self.paths["adjoint_sources"] = os.path.join(
            root_path, "ADJOINT_SOURCES_AND_WINDOWS", "ADJOINT_SOURCES")

        # Station file subfolders.
        self.paths["dataless_seed"] = os.path.join(self.paths["stations"],
                                                   "SEED")
        self.paths["station_xml"] = os.path.join(self.paths["stations"],
                                                 "StationXML")
        self.paths["resp"] = os.path.join(self.paths["stations"],
                                          "RESP")

        # Paths for various files.
        self.paths["config_file"] = os.path.join(root_path,
                                                 "config.xml")
        self.paths["config_file_cache"] = \
            os.path.join(self.paths["cache"], "config.xml_cache.pickle")
        self.paths["inv_db_file"] = \
            os.path.join(self.paths["cache"], "inventory_db.sqlite")

    def __update_folder_structure(self):
        """
        Updates the folder structure of the project.
        """
        for name, path in self.paths.iteritems():
            if "file" in name or os.path.exists(path):
                continue
            os.makedirs(path)
        events = self.comm.events.list()
        folders = [self.paths["data"], self.paths["synthetics"]]
        for folder in folders:
            for event in events:
                event_folder = os.path.join(folder, event)
                if os.path.exists(event_folder):
                    continue
                os.makedirs(event_folder)

    def __init_new_project(self, project_name):
        """
        Initializes a new project. This currently just means that it creates a
        default config file. The folder structure is checked and rebuilt every
        time the project is initialized anyways.
        """
        from lxml import etree
        from lxml.builder import E

        if not project_name:
            project_name = "LASIFProject"

        doc = E.lasif_project(
            E.name(project_name),
            E.description(""),
            E.download_settings(
                E.seconds_before_event(str(300)),
                E.seconds_after_event(str(3600)),
                E.interstation_distance_in_m(str(1000.0)),
                E.channel_priorities(
                    E.priority("BH[Z,N,E]"),
                    E.priority("LH[Z,N,E]"),
                    E.priority("HH[Z,N,E]"),
                    E.priority("EH[Z,N,E]"),
                    E.priority("MH[Z,N,E]")),
                E.location_priorities(
                    E.priority(""),
                    E.priority("00"),
                    E.priority("10"),
                    E.priority("20"),
                    E.priority("01"),
                    E.priority("02"))
            ),
            E.domain(
                getattr(E, "global")("false"),
                E.domain_bounds(
                    E.minimum_longitude(str(-20)),
                    E.maximum_longitude(str(20)),
                    E.minimum_latitude(str(-20)),
                    E.maximum_latitude(str(20)),
                    E.minimum_depth_in_km(str(0.0)),
                    E.maximum_depth_in_km(str(200.0)),
                    E.boundary_width_in_degree(str(3.0))),
                E.domain_rotation(
                    E.rotation_axis_x(str(1.0)),
                    E.rotation_axis_y(str(1.0)),
                    E.rotation_axis_z(str(1.0)),
                    E.rotation_angle_in_degree(str(-45.0)))))

        string_doc = etree.tostring(doc, pretty_print=True,
                                    xml_declaration=True, encoding="UTF-8")

        with open(self.paths["config_file"], "wt") as open_file:
            open_file.write(string_doc)

    def get_output_folder(self, tag):
        """
        Generates a output folder in a unified way.
        """
        from obspy import UTCDateTime
        output_dir = ("%s___%s" % (str(UTCDateTime()), tag))
        output_dir = os.path.join(self.paths["output"], output_dir)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        return output_dir
