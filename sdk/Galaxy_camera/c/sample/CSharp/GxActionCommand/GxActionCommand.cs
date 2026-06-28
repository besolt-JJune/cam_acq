using System.Runtime.InteropServices;
using GxIAPINET;

namespace GxActionCommand
{
    static class Sample
    {
        // Check if all cameras support ActionCommand and ptp functions
        static void CheckCamParameters(List<IGXDevice> lstDevPtr, List<IGXFeatureControl> lstRemoteFeature)
        {
            Console.WriteLine("check is all device support ActionCommand and PTP");

            bool bIsAllDevSupport = true;
            for (int i = 0; i < lstRemoteFeature.Count; i++)
            {
                List<string> lstEnumValue = lstRemoteFeature[i].GetEnumFeature("GevSupportedOptionSelector").GetEnumEntryList();

                bool bActionItemExist = false;
                bool bScheduledActionItemExist = false;
                bool bPtpItemExist = false;

                bool bActionSupport = false;
                bool bScheduledActionSupport = false;
                bool bPtpSupport = false;

                foreach (string EnumValue in lstEnumValue)
                {
                    if (EnumValue.Equals("Action"))
                    {
                        bActionItemExist = true;
                    }

                    if (EnumValue.Equals("ScheduledAction"))
                    {
                        bScheduledActionItemExist = true;
                    }

                    if (EnumValue.Equals("Ptp"))
                    {
                        bPtpItemExist = true;
                    }
                }

                if (bActionItemExist && bScheduledActionItemExist && bPtpItemExist)
                {
                    lstRemoteFeature[i].GetEnumFeature("GevSupportedOptionSelector").SetValue("Action");

                    bActionSupport = lstRemoteFeature[i].GetBoolFeature("GevSupportedOption").GetValue();

                    lstRemoteFeature[i].GetEnumFeature("GevSupportedOptionSelector").SetValue("ScheduledAction");

                    bScheduledActionSupport = lstRemoteFeature[i].GetBoolFeature("GevSupportedOption").GetValue();

                    lstRemoteFeature[i].GetEnumFeature("GevSupportedOptionSelector").SetValue("Ptp");

                    bPtpSupport = lstRemoteFeature[i].GetBoolFeature("GevSupportedOption").GetValue();

                    if (bActionSupport && bScheduledActionSupport && bPtpSupport)
                    {
                        // current cam support Action ScheduledAction Ptp
                    }
                    else
                    {
                        string SN = lstDevPtr[i].GetDeviceInfo().GetSN();
                        Console.WriteLine("SN:{0} don't support ActionCommand or PTP", SN);
                        bIsAllDevSupport = false;
                    }
                }
                else
                {
                    string SN = lstDevPtr[i].GetDeviceInfo().GetSN();
                    Console.WriteLine("SN:{0} don't support ActionCommand or PTP", SN);
                    bIsAllDevSupport = false;
                }
            }

            if (!bIsAllDevSupport)
            {
                throw new CGalaxyException((int)GX_STATUS_LIST.GX_STATUS_ERROR, "not all cam support ActionCommand and PTP");
            }
            else
            {
                Console.WriteLine("successful check, all device support ActionCommand and PTP");
            }
        }

        // Setting cam parameters
        static void SetCamParametersAndStartAcquisition(List<IGXDevice> lstDevPtr
            , List<IGXFeatureControl> lstRemoteFeature
            , List<IGXStream> lstStream)
        {
            Console.WriteLine("setting cam ActionCommand parameters");

            for (int i = 0; i < lstRemoteFeature.Count; i++)
            {
                // Load default parameter group
                lstRemoteFeature[i].GetEnumFeature("UserSetSelector").SetValue("Default");

                lstRemoteFeature[i].GetCommandFeature("UserSetLoad").Execute();

                // Trigger Mode On
                lstRemoteFeature[i].GetEnumFeature("TriggerMode").SetValue("On");

                // Trigger source set to Action0
                lstRemoteFeature[i].GetEnumFeature("TriggerSource").SetValue("Action0");

                // Setting cam ActionCommand parameters
                lstRemoteFeature[i].GetIntFeature("ActionDeviceKey").SetValue(1);

                lstRemoteFeature[i].GetIntFeature("ActionGroupKey").SetValue(1);

                lstRemoteFeature[i].GetIntFeature("ActionGroupMask").SetValue(0xFFFFFFFF);

                // Start Acquisition
                lstStream[i].StartGrab();

                lstRemoteFeature[i].GetCommandFeature("AcquisitionStart").Execute();
            }

            Console.WriteLine("setting success");
        }

        // Demonstrate ActionCommand function
        static void ShowActionCommand(List<IGXDevice> lstDevPtr
            , List<IGXStream> lstStream
            , ref IntPtr pBuff)
        {
            Console.WriteLine("demonstrate ActionCommand function");

            UInt32 DeviceKey = 1;
            UInt32 GroupKey = 1;
            UInt32 GroupMask = 0xffffffff;
            string SpecialIP = "";
            UInt32 NumResult = (UInt32)lstDevPtr.Count;
            GX_GIGE_ACTION_COMMAND_RESULT[] Result = new GX_GIGE_ACTION_COMMAND_RESULT[NumResult];
            int size = Marshal.SizeOf(typeof(GX_GIGE_ACTION_COMMAND_RESULT)) * (int)NumResult;
            pBuff = Marshal.AllocHGlobal(size);

            // pBoardCastAddress can be broadcast IP (255.255.255.255), subnet broadcast (192.168.42.255), unicast (192.168.42.42)
            string IP = "255.255.255.255";

            IGXFactory.GetInstance().GigEIssueActionCommand(DeviceKey, GroupKey, GroupMask
                , IP, SpecialIP, 500, ref NumResult, pBuff);

            for (int i = 0; i < NumResult; i++)
            {
                IntPtr Ptr = new IntPtr(pBuff.ToInt64() + Marshal.SizeOf(typeof(GX_GIGE_ACTION_COMMAND_RESULT)) * i);
                Result[i] = (GX_GIGE_ACTION_COMMAND_RESULT)Marshal.PtrToStructure(Ptr, typeof(GX_GIGE_ACTION_COMMAND_RESULT));
            }

            // print ack
            for (UInt32 i = 0; i < NumResult; i++)
            {
                Console.WriteLine("Ack Return ip:{0}, status:{1}"
                    , System.Text.Encoding.UTF8.GetString(Result[i].DeviceAddress).TrimEnd('\0')
                    , Result[i].Status);
            }

            // get image
            for (int i = 0; i < lstDevPtr.Count; i++)
            {
                IFrameData Image = null;
                Image = lstStream[i].DQBuf(1000);

                Console.WriteLine("SN:{0} get image success, image status:{1}"
                    , lstDevPtr[i].GetDeviceInfo().GetSN()
                    , ((Image.GetStatus() == GX_FRAME_STATUS_LIST.GX_FRAME_STATUS_SUCCESS) ? "complete frame" : "incomplete frame"));

                lstStream[i].QBuf(Image);
            }
        }

        // Demonstrate the ScheduledActionCommand function
        static void ShowScheduledActionCommand(List<IGXDevice> lstDevPtr
            , List<IGXFeatureControl> lstRemoteFeature
            , List<IGXStream> lstStream
            , ref IntPtr pBuff)
        {
            UInt32 DeviceKey = 1;
            UInt32 GroupKey = 1;
            UInt32 GroupMask = 0xffffffff;
            string SpecialIP = "";
            UInt32 NumResult = (UInt32)lstDevPtr.Count;
            GX_GIGE_ACTION_COMMAND_RESULT[] Result = new GX_GIGE_ACTION_COMMAND_RESULT[NumResult];

            // pBoardCastAddress can be broadcast IP (255.255.255.255), subnet broadcast (192.168.42.255), unicast (192.168.42.42)
            string IP = "255.255.255.255";

            // Setting cam PTP parameters
            Console.WriteLine("setting cam PTP parameters");

            for (int i = 0; i < lstRemoteFeature.Count; i++)
            {
                // PTP enable
                lstRemoteFeature[i].GetBoolFeature("PtpEnable").SetValue(true);
            }

            // First, you should wait for the camera to assign the role, which takes about 8s, 
            // and the judgment method is to read the PtpStatus cyclically until the value is "Master" or "Slave", the role assignment is completed.
            //
            // Then carry out time calibration, accuracy to within 1us need time about 1~2min,
            // the judgment method is to continuously set the PtpDataSetLatch of the Slave camera and read the PtpOffsetFromMaster, 
            // you can get the time deviation of the Slave relative to the Master,  
            // when the PtpOffsetFromMaster absolute value is less than the user's desired time accuracy, time calibration is complete.
            string Cam0PtpStatus = lstRemoteFeature[0].GetEnumFeature("PtpStatus").GetValue();

            int Loops = 0;
            bool bStatusOK = (Cam0PtpStatus.Equals("Master") || (Cam0PtpStatus.Equals("Slave")));

            while (!bStatusOK && Loops < 8)
            {
                Thread.Sleep(1000);
                Loops++;

                Cam0PtpStatus = lstRemoteFeature[0].GetEnumFeature("PtpStatus").GetValue();

                bStatusOK = (Cam0PtpStatus.Equals("Master") || (Cam0PtpStatus.Equals("Slave")));
            }

            if (!bStatusOK)
            {
                throw new CGalaxyException((int)GX_STATUS_LIST.GX_STATUS_ERROR, "PTP time calibration timeout");
            }

            Console.WriteLine("setting success");

            // Demonstrate the ScheduledActionCommand function
            Console.WriteLine("demonstrate ScheduledActionCommand function");

            // Get the current timestamp of the camera(ns), and plan for the camera to pick an image in 5s.
            lstRemoteFeature[0].GetCommandFeature("TimestampLatch").Execute();
            Int64 TimeStamp = lstRemoteFeature[0].GetIntFeature("TimestampLatchValue").GetValue();
            TimeStamp += 5000000000;

            IGXFactory.GetInstance().GigEIssueScheduledActionCommand(DeviceKey, GroupKey, GroupMask
                , (UInt64)TimeStamp, IP, SpecialIP, 500, ref NumResult, pBuff);

            // Waiting for the camera to execute
            Thread.Sleep(5000);

            for (int i = 0; i < NumResult; i++)
            {
                IntPtr Ptr = new IntPtr(pBuff.ToInt64() + Marshal.SizeOf(typeof(GX_GIGE_ACTION_COMMAND_RESULT)) * i);
                Result[i] = (GX_GIGE_ACTION_COMMAND_RESULT)Marshal.PtrToStructure(Ptr, typeof(GX_GIGE_ACTION_COMMAND_RESULT));
            }

            // print ack
            for (UInt32 i = 0; i < NumResult; i++)
            {
                Console.WriteLine("Ack Return ip:{0}, status:{1}"
                    , System.Text.Encoding.UTF8.GetString(Result[i].DeviceAddress).TrimEnd('\0')
                    , Result[i].Status);
            }

            // get image
            for (int i = 0; i < lstDevPtr.Count; i++)
            {
                IFrameData Image = null;
                Image = lstStream[i].DQBuf(1000);

                Console.WriteLine("SN:{0} get image success, image status:{1}"
                    , lstDevPtr[i].GetDeviceInfo().GetSN()
                    , ((Image.GetStatus() == GX_FRAME_STATUS_LIST.GX_FRAME_STATUS_SUCCESS) ? "complete frame" : "incomplete frame"));

                lstStream[i].QBuf(Image);
            }
        }

        // Stop Acquisition and close cam
        static void StopAcquisitionAndCloseCam(List<IGXDevice> lstDevPtr
            , List<IGXFeatureControl> lstRemoteFeature
            , List<IGXStream> lstStream)
        {
            for (int i = 0; i < lstRemoteFeature.Count; i++)
            {
                try
                {
                    lstRemoteFeature[i].GetCommandFeature("AcquisitionStop").Execute();
                }
                catch (Exception e)
                {
                    Console.WriteLine("cam idx:{0} stop acquisition fail!", i);
                    continue;
                }
            }

            for (int i = 0; i < lstStream.Count; i++)
            {
                try
                {
                    lstStream[i].Close();
                }
                catch (Exception e)
                {
                    Console.WriteLine("cam idx:{0} close stream fail!", i);
                    continue;
                }
            }

            for (int i = 0; i < lstDevPtr.Count; i++)
            {
                try
                {
                    lstDevPtr[i].Close();
                }
                catch (Exception e)
                {
                    Console.WriteLine("cam idx:{0} close device fail!", i);
                    continue;
                }
            }
        }

        static void Main()
        {
            List<IGXDevice> lstDevPtr = new List<IGXDevice>();
            List<IGXFeatureControl> lstRemoteFeature = new List<IGXFeatureControl>();
            List<IGXStream> lstStream = new List<IGXStream>();
            IntPtr pBuff = IntPtr.Zero;

            try
            {
                IGXFactory.GetInstance().Init();

                List<IGXDeviceInfo> lstDevInfo = new List<IGXDeviceInfo>();

                // Enumerate gige devices
                IGXFactory.GetInstance().UpdateAllDeviceListEx((ulong)GX_TL_TYPE_LIST.GX_TL_TYPE_GEV, 1000, lstDevInfo);

                // Requires number of devices greater than or equal to 1
                if (lstDevInfo.Count < 1)
                {
                    throw new CGalaxyException((int)GX_STATUS_LIST.GX_STATUS_ERROR, "Gige device less than 1!");
                }

                Console.WriteLine("open device");

                foreach (IGXDeviceInfo info in lstDevInfo)
                {
                    // Open all enumerated gige cam via SN
                    IGXDevice objDevPtr = IGXFactory.GetInstance().OpenDeviceBySN(info.GetSN(), GX_ACCESS_MODE.GX_ACCESS_EXCLUSIVE);
                    lstDevPtr.Add(objDevPtr);

                    // Get Remote Attribute Controller
                    IGXFeatureControl objRemoteFeature = objDevPtr.GetRemoteFeatureControl();
                    lstRemoteFeature.Add(objRemoteFeature);

                    // Open Stream
                    uint StreamCount = objDevPtr.GetStreamCount();

                    if (StreamCount > 0)
                    {
                        IGXStream objStream = objDevPtr.OpenStream(0);
                        lstStream.Add(objStream);
                    }
                    else
                    {
                        throw new CGalaxyException((int)GX_STATUS_LIST.GX_STATUS_ERROR, "Not find stream!");
                    }

                    Console.WriteLine("<Model Name:{0}> <Serial Number:{1}>"
                        , info.GetModelName(), info.GetSN());
                }

                // Check if all cameras support ActionCommand and ptp functions
                CheckCamParameters(lstDevPtr, lstRemoteFeature);

                // Setting cam parameters and start acquisition
                SetCamParametersAndStartAcquisition(lstDevPtr, lstRemoteFeature, lstStream);

                // Demonstrate ActionCommand function
                ShowActionCommand(lstDevPtr, lstStream, ref pBuff);

                // Demonstrate the ScheduledActionCommand function
                ShowScheduledActionCommand(lstDevPtr, lstRemoteFeature, lstStream, ref pBuff);

                // Stop Acquisition and close cam
                StopAcquisitionAndCloseCam(lstDevPtr, lstRemoteFeature, lstStream);

                IGXFactory.GetInstance().Uninit();
            }
            catch (CGalaxyException e)
            {
                Console.WriteLine("<Get Galaxy Exception:{0}> <{1}>"
                    , e.GetErrorCode(), e.Message);

                // Stop Acquisition and close cam
                StopAcquisitionAndCloseCam(lstDevPtr, lstRemoteFeature, lstStream);

                IGXFactory.GetInstance().Uninit();
            }
            catch (Exception e)
            {
                Console.WriteLine("<Get Unknow Error:{0}>"
                    , e.Message);

                IGXFactory.GetInstance().Uninit();
            }

            if (pBuff != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(pBuff);
            }

            Console.WriteLine("App exit!");
            Console.Read();

            return;
        }
    }
}