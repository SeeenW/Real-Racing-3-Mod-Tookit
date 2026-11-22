
//%include utility.xsh
// Jesse: Added support for specmask, looks up another texture for to modulate the specular and reflection. commented out waiting for support for all cars unique textures.

#ifndef ENABLE_SHADER_FEATURES

#ifdef DONT_USE_CAR_REFLECTION //~???
	#ifdef CUBE_MAP
	#undef CUBE_MAP
	#endif
#else
	#ifndef CUBE_MAP
	#define CUBE_MAP
	#endif
#endif

#ifdef DONT_USE_CAR_SPECULAR //~???
	#ifdef SINGLE_SPEC
	#undef SINGLE_SPEC
	#endif
	#ifdef DOUBLE_SPEC
	#undef DOUBLE_SPEC
	#endif
#endif

#ifndef SUN_FOG
#define SUN_FOG
#endif

#endif//ENABLE_SHADER_FEATURES

//%include carf.xsh





