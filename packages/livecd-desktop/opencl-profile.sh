# livecd-desktop: on Adreno, let programs started outside the desktop session, such as OpenCL
# through clvk, also see the desktop's Turnip driver. The session sets its own Vulkan driver,
# and phones without /dev/kgsl-3d0 (Mali) are left alone.
livecd_turnip_icd="$HOME/.local/opt/livecd-native/gpu/share/vulkan/icd.d/freedreno_icd.aarch64.json"
if [ -z "${VK_ICD_FILENAMES}${VK_DRIVER_FILES}" ] && [ -e /dev/kgsl-3d0 ] && [ -f "$livecd_turnip_icd" ]; then
	case ":${VK_ADD_DRIVER_FILES}:" in
	*":$livecd_turnip_icd:"*) ;;
	*) export VK_ADD_DRIVER_FILES="$livecd_turnip_icd${VK_ADD_DRIVER_FILES:+:$VK_ADD_DRIVER_FILES}" ;;
	esac
fi
unset livecd_turnip_icd
